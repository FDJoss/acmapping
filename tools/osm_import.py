"""Turn cached OpenStreetMap data into designer layouts for every catalogue track.

usage: python -I osm_import.py <cache_dir> <builder_dir> <library.json> <report.txt> [contact.html] [--only id,id]

For each track:
  1. candidate loops: each OSM `type=circuit` relation near the venue, plus the raceway network
  2. pick the simple loop whose length is closest to the official lap length
  3. orient it (OSM oneway race tags, else the catalogue direction)
  4. smooth the trace a little and fit designer control points to within ~1 m
  5. start/finish beside the pit lane (ovals: middle of the front straight), pit side from the pit lane
  6. banking: ovals from published specs per turn; road courses copy their oval's banking where they share it
  7. sanity checks: narrow the road where sections are too close or hairpins too tight; reject crossings
"""
import html
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from osm_fetch import cache_name  # noqa: E402
from track_catalog import DEFAULT_WIDTH, SERIES_PITS, TRACKS  # noqa: E402

R_EARTH = 6378137.0
ELEV_CACHE = "elevation_cache.json"        # set from the command line (lives in the OSM cache folder)
PIT_RE = re.compile(r"\bpit|stands|\bbox|boxen|boxes|paddock|pitlane|pit lane|voie des", re.I)
EXCLUDE_RE = re.compile(r"\bpit|stands|\bbox|boxen|paddock|kart|drag|dirt|skid|\btest|access|service|run-?off|escape|"
                        r"service road|junior|short track|motocross|rally", re.I)
BAD_SURFACE = {"dirt", "gravel", "unpaved", "ground", "grass", "sand", "fine_gravel", "compacted"}


# ---------------------------------------------------------------- OSM loading
def load_osm(path):
    d = json.load(open(path, encoding="utf-8"))
    nodes, ways, rels = {}, {}, []
    for el in d.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lat"], el["lon"])
        elif el["type"] == "way":
            ways[el["id"]] = dict(nodes=el.get("nodes", []), tags=el.get("tags", {}))
        elif el["type"] == "relation":
            rels.append(dict(id=el["id"], tags=el.get("tags", {}), members=el.get("members", [])))
    return nodes, ways, rels


def is_pit(tags, role=""):
    if role and "pit" in role.lower():
        return True
    if PIT_RE.search(tags.get("name", "")):
        return True
    return tags.get("raceway", "") in ("pit_lane", "pitlane", "pit") or tags.get("service") == "pit_lane"


def excluded(tags):
    if EXCLUDE_RE.search(tags.get("name", "")):
        return True
    if tags.get("sport") == "karting" or tags.get("surface") in BAD_SURFACE:
        return True
    return tags.get("raceway", "") in ("pit_lane", "pitlane", "karting", "drag_strip", "kart")


class Proj:
    def __init__(self, lat0, lon0):
        self.lat0, self.lon0, self.c = lat0, lon0, math.cos(math.radians(lat0))

    def __call__(self, ll):
        return (math.radians(ll[1] - self.lon0) * R_EARTH * self.c, math.radians(ll[0] - self.lat0) * R_EARTH)

    def inverse(self, x, y):
        """Local metres back to (lat, lon) arrays."""
        return (self.lat0 + np.degrees(np.asarray(y) / R_EARTH),
                self.lon0 + np.degrees(np.asarray(x) / (R_EARTH * self.c)))


# ---------------------------------------------------------------- graph + loop search
def build_graph(way_ids, ways, nodes, proj, heal=12.0):
    use = defaultdict(int)
    for w in way_ids:
        ns = [n for n in ways[w]["nodes"] if n in nodes]
        for n in ns:
            use[n] += 1
        if ns:
            use[ns[0]] += 1
            use[ns[-1]] += 1
    # Mappers sometimes leave a small gap where two ways should meet. Join a loose way end to the nearest node
    # of another way within `heal` metres, so the loop can still close.
    links = []
    xy = {n: proj(nodes[n]) for w in way_ids for n in ways[w]["nodes"] if n in nodes}
    owner = defaultdict(set)
    for w in way_ids:
        for n in ways[w]["nodes"]:
            owner[n].add(w)
    loose = [n for n, c in use.items() if c == 2 and len(owner[n]) == 1]     # an end touching nothing else
    if loose and heal > 0:
        all_n = np.array(list(xy.keys()))
        all_p = np.array([xy[n] for n in all_n])
        for e in loose:
            w = next(iter(owner[e]))
            ns = [n for n in ways[w]["nodes"] if n in nodes]
            prev = ns[-2] if ns[-1] == e else ns[1]                 # the way's direction arriving at this end
            out = np.array(xy[e]) - np.array(xy[prev])
            out /= (np.linalg.norm(out) or 1.0)
            d = np.hypot(all_p[:, 0] - xy[e][0], all_p[:, 1] - xy[e][1])
            gapv = (all_p - np.array(xy[e]))
            ahead = (gapv @ out) > 0.5 * np.maximum(d, 1e-6)          # only carry on forward, never U-turn
            mask = np.array([not (owner[n] & owner[e]) for n in all_n]) & (ahead | (d < 1.0))
            if not mask.any():
                continue
            d[~mask] = np.inf
            j = int(np.argmin(d))
            if d[j] <= heal:
                n2 = int(all_n[j])
                links.append((e, n2, float(d[j])))
                use[n2] += 2
    edges = []
    for e, n2, dlen in links:
        if dlen > 0.5:
            edges.append(dict(u=e, v=n2, nodes=[e, n2], pts=[xy[e], xy[n2]], length=dlen, way=None))
    for w in way_ids:
        ns = [n for n in ways[w]["nodes"] if n in nodes]
        if len(ns) < 2:
            continue
        start = 0
        for k in range(1, len(ns)):
            if use[ns[k]] >= 2 or k == len(ns) - 1:
                seg = ns[start:k + 1]
                pts = [proj(nodes[n]) for n in seg]
                ln = sum(math.dist(pts[j], pts[j + 1]) for j in range(len(pts) - 1))
                if ln > 0.5:
                    edges.append(dict(u=seg[0], v=seg[-1], nodes=seg, pts=pts, length=ln, way=w))
                start = k
    return edges


def best_cycle(edges, target, tol=0.08, max_steps=4_000_000, keep=300):
    """All simple loops within `tol` of the target length (best `keep` of them), best first."""
    adj = defaultdict(list)
    found = []

    def offer(sc, cyc, ln):
        found.append((sc, cyc, ln))
        if len(found) > 4 * keep:
            found.sort(key=lambda f: f[0])
            del found[keep:]

    for k, e in enumerate(edges):
        if e["u"] == e["v"]:
            sc = abs(e["length"] - target) / target
            if sc <= tol:
                offer(sc, [(k, True)], e["length"])
            continue
        adj[e["u"]].append((k, e["v"], True))
        adj[e["v"]].append((k, e["u"], False))
    nodes = sorted(adj)
    order = {n: i for i, n in enumerate(nodes)}
    bound = target * (1 + tol)
    steps = 0
    sys.setrecursionlimit(10000)
    for s in nodes:
        # shortest distance back to s, using only nodes "after" s (each cycle is found from its lowest node)
        dist = {s: 0.0}
        frontier = [(0.0, s)]
        import heapq
        while frontier:
            dd, n = heapq.heappop(frontier)
            if dd > dist.get(n, math.inf) or dd > bound:
                continue
            for k, m2, _ in adj[n]:
                if order[m2] < order[s]:
                    continue
                nd = dd + edges[k]["length"]
                if nd < dist.get(m2, math.inf):
                    dist[m2] = nd
                    heapq.heappush(frontier, (nd, m2))
        visited = {s}
        path = []

        def dfs(node, length):
            nonlocal steps
            steps += 1
            if steps > max_steps:
                return
            for k, nxt, fwd in adj[node]:
                if path and k == path[-1][0]:
                    continue
                nl = length + edges[k]["length"]
                if nl > bound:
                    continue
                if nxt == s:
                    sc = abs(nl - target) / target
                    if sc <= tol:
                        offer(sc, path + [(k, fwd)], nl)
                    continue
                if order[nxt] <= order[s] or nxt in visited or nl + dist.get(nxt, math.inf) > bound:
                    continue
                visited.add(nxt)
                path.append((k, fwd))
                dfs(nxt, nl)
                path.pop()
                visited.discard(nxt)

        dfs(s, 0.0)
        if steps > max_steps:
            break
    found.sort(key=lambda f: f[0])
    return found[:keep], steps > max_steps


def euler_loop(edges, role_of):
    """Follow every edge exactly once (a circuit relation lists exactly the streets of one layout, and a street
    circuit may pass through the same junction twice). Uses the members' forward/backward roles as the race
    direction when every member has one. Returns (loop, length, directed) or None."""
    if not edges:
        return None
    directed = all(e["way"] is not None and role_of.get(e["way"]) in ("forward", "backward") for e in edges)
    adj = defaultdict(list)
    bal = defaultdict(int)
    for k, e in enumerate(edges):
        if directed:
            fwd = role_of[e["way"]] == "forward"
            a, b = (e["u"], e["v"]) if fwd else (e["v"], e["u"])
            adj[a].append((k, b, fwd))
            bal[a] += 1
            bal[b] -= 1
        else:
            adj[e["u"]].append((k, e["v"], True))
            adj[e["v"]].append((k, e["u"], False))
            bal[e["u"]] += 1
            bal[e["v"]] += 1
    if directed and any(v != 0 for v in bal.values()):
        return None
    if not directed and any(v % 2 for v in bal.values()):
        return None
    used, ptr, circuit = set(), defaultdict(int), []
    stack = [(edges[0]["u"] if not directed or edges[0]["way"] is None or role_of[edges[0]["way"]] == "forward"
              else edges[0]["v"], None)]
    while stack:
        node, via = stack[-1]
        lst = adj[node]
        while ptr[node] < len(lst) and lst[ptr[node]][0] in used:
            ptr[node] += 1
        if ptr[node] < len(lst):
            k, nxt, fwd = lst[ptr[node]]
            used.add(k)
            stack.append((nxt, (k, fwd)))
        else:
            stack.pop()
            if via is not None:
                circuit.append(via)
    if len(used) != len(edges):
        return None                                     # more than one piece
    circuit.reverse()
    return circuit, sum(edges[k]["length"] for k, _ in circuit), directed


OTHER_LAYOUT_RE = re.compile(r"road course|infield|chicane|roval|small oval|bullring|half.?mile|quarter.?mile|dirt", re.I)


def hull_perimeter(P):
    pts = sorted(map(tuple, P))
    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h
    hull = half(pts)[:-1] + half(pts[::-1])[:-1]
    return sum(math.dist(hull[i], hull[(i + 1) % len(hull)]) for i in range(len(hull)))


def rank_loop(cand, edges, ways, kind, is_rel):
    """Lower is better: length error, plus for ovals a convexity and other-layout-name penalty."""
    sc, cyc, ln = cand
    total = sc - (0.01 if is_rel else 0.0)
    P, _ = cycle_polyline(edges, cyc)
    # a real track encloses a fair area for its length; thin strips (e.g. drag-strip lanes) don't
    if 4 * math.pi * abs(signed_area(P)) / (ln * ln) < 0.05:
        return math.inf
    if kind == "oval":
        total += 2.0 * (ln / hull_perimeter(P) - 1.0)
        other = sum(edges[k]["length"] for k, _ in cyc
                    if edges[k]["way"] is not None and OTHER_LAYOUT_RE.search(ways[edges[k]["way"]]["tags"].get("name", "")))
        total += 1.0 * other / ln
    return total


def cycle_polyline(edges, cyc):
    pts, segs = [], []
    for k, fwd in cyc:
        p = edges[k]["pts"] if fwd else edges[k]["pts"][::-1]
        segs.append((k, fwd, len(pts)))
        pts.extend(p[:-1])
    return np.array(pts), segs


# ---------------------------------------------------------------- geometry helpers
def densify(P, step=1.0, vflags=None):
    """Resample a closed polyline every `step` m. With vflags (one per segment i -> i+1) also return the flag
    of the segment each new point lies on."""
    Q = np.vstack([P, P[:1]])
    seg = np.hypot(*(Q[1:] - Q[:-1]).T)
    keep = seg > 1e-6
    Q = np.vstack([Q[:-1][keep], Q[:1]])
    seg = seg[keep]
    cum = np.concatenate([[0], np.cumsum(seg)])
    S = np.arange(0, cum[-1], step)
    idx = np.clip(np.searchsorted(cum, S, side="right") - 1, 0, len(seg) - 1)
    f = (S - cum[idx]) / seg[idx]
    pts = Q[idx] + (Q[idx + 1] - Q[idx]) * f[:, None]
    if vflags is None:
        return pts, cum[-1]
    return pts, cum[-1], np.asarray(vflags)[keep][idx]


def covered(tags):
    """Track in a tunnel, under cover or on a bridge: the terrain model doesn't show the road's height there."""
    return (tags.get("tunnel", "no") != "no" or tags.get("bridge", "no") != "no" or tags.get("covered") == "yes")


def smooth_1d(v, sigma):
    """Gaussian smoothing of a circular 1-D series (sigma in samples)."""
    if sigma <= 0.3:
        return v
    half = int(3 * sigma) + 1
    kern = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma) ** 2)
    kern /= kern.sum()
    w = np.take(v, np.arange(-half, len(v) + half), mode="wrap")     # works even when the window exceeds the lap
    return np.convolve(w, kern, mode="same")[half:half + len(v)]


def dem_source(lat, lon):
    """Which OpenTopoData dataset answers for this place: ned10m (lower 48 US states), eudem25m (Europe), else SRTM."""
    if 24 <= lat <= 50 and -125 <= lon <= -66:
        return "ned"
    if 34 <= lat <= 72 and -25 <= lon <= 45:
        return "eudem"
    return "srtm"


def ground_profile(t, m, proj, flag_spl, bank_samples, half, cache_path, notes):
    """Smoothed terrain height (m, lowest point = 0) at every sample of the fitted spline.
    Banked samples are taken just inside the low edge (the ground the banking rises from); tunnels and bridges
    are bridged over from either end; SRTM noise and city buildings are filtered with a median then a Gaussian."""
    import elevation
    N, h, L = m["N"], m["h"], m["L"]
    if t.get("elevation") == "flat":
        notes.append("elevation: kept flat (terrain data unreliable here)")
        return np.zeros(N)
    X, Y = np.array(m["x"]), np.array(m["y"])
    k = curvature(X, Y, h, 20)
    nx = -(np.roll(Y, -2) - np.roll(Y, 2))
    ny = np.roll(X, -2) - np.roll(X, 2)
    ln = np.hypot(nx, ny)
    ln[ln == 0] = 1
    nx, ny = nx / ln, ny / ln                                   # left normal
    infield = 1.0 if signed_area(np.column_stack([X, Y])) > 0 else -1.0
    step = max(1, int(round(10 / h)))
    idx = np.arange(0, N, step)
    low = np.where(np.abs(k[idx]) > 1 / 2000, np.sign(k[idx]), infield)   # inside of the turn
    off = np.where(bank_samples[idx] > 3, half + 2.0, 0.0) * low
    sx, sy = X[idx] + nx[idx] * off, Y[idx] + ny[idx] * off
    lat, lon = proj.inverse(sx, sy)
    raw = elevation.lookup(list(zip(lat, lon)), cache_path, log=lambda s: print(s, flush=True))
    e = np.array([np.nan if v is None else float(v) for v in raw])
    nodata = int(np.isnan(e).sum())
    e[flag_spl[idx]] = np.nan
    if (~np.isnan(e)).sum() < 4:
        notes.append("no elevation data: left flat")
        return np.zeros(N)
    s = idx * h
    good = ~np.isnan(e)
    e = np.interp(s, s[good], e[good], period=L)
    if flag_spl.any():
        notes.append(f"elevation bridged over {flag_spl.mean() * 100:.0f}% of the lap (tunnels/bridges)")
    if nodata:
        notes.append(f"{nodata} elevation samples had no data and were filled in")
    # Buildings, trees and structures only ever add height, and they're narrower than real hills: remove bumps
    # narrower than the window with a morphological opening (rolling minimum, then rolling maximum).
    open_m = {"oval": 60.0, "street": 150.0, "road": 40.0}[t["kind"]]
    ko = max(1, int(round(open_m / (step * h) / 2)))
    win = np.arange(-ko, ko + 1)
    e = np.array([np.min(np.take(e, i + win, mode="wrap")) for i in range(len(e))])
    e = np.array([np.max(np.take(e, i + win, mode="wrap")) for i in range(len(e))])
    med_m, sig_m = {"oval": (200.0, 150.0), "street": (150.0, 60.0), "road": (50.0, 25.0)}[t["kind"]]
    if dem_source(t["lat"], t["lon"]) == "srtm":
        # outside the USA and Europe the only source is 30 m SRTM radar data, which wobbles by several metres
        # over trees and structures: smooth those wobbles away, keeping hills that span a few hundred metres
        sig_m = max(sig_m, 80.0)
        notes.append("elevation from SRTM (30 m): smoothed more heavily")
    kw = max(1, int(round(med_m / (step * h) / 2)))
    e = np.array([np.median(np.take(e, np.arange(i - kw, i + kw + 1), mode="wrap")) for i in range(len(e))])
    e = smooth_1d(e, sig_m / (step * h))
    G = np.interp(np.arange(N) * h, s, e, period=L)
    return G - G.min()


def smooth_loop(D, sigma):
    if sigma <= 0:
        return D
    half = int(3 * sigma)
    kern = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma) ** 2)
    kern /= kern.sum()
    n = len(D)
    W = np.vstack([D[-half:], D, D[:half]])
    return np.column_stack([np.convolve(W[:, i], kern, mode="same")[half:half + n] for i in (0, 1)])


def signed_area(P):
    return 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])


def curvature(X, Y, h, win_m):
    w = max(1, int(round(win_m / h)))
    hd = np.arctan2(np.roll(Y, -1) - Y, np.roll(X, -1) - X)
    dh = (np.roll(hd, -w) - np.roll(hd, w) + np.pi) % (2 * np.pi) - np.pi
    return dh / (2 * w * h)                       # signed, + = left


# ---------------------------------------------------------------- fitting
def fit_points(lc, D, kind, s_first):
    """Greedy fit of control points to the densified loop D (1 m spacing). Point 0 sits at index s_first."""
    n = len(D)
    tol, min_gap = 1.0, (min(45.0, n / 40.0) if kind == "oval" else 10.0)     # short ovals need closer points
    init = (n / 16.0) if kind == "oval" else 140.0
    ctrl = sorted({int(round(s_first + k * init)) % n for k in range(int(n / init))} | {s_first % n})
    for _ in range(80):
        cs = sorted(ctrl, key=lambda s: (s - s_first) % n)
        pts = [dict(x=float(D[s][0]), y=float(D[s][1])) for s in cs]
        m = lc.build_centerline(pts, 0.0)
        C = np.column_stack([m["x"], m["y"]])
        Ns = len(C)
        # deviation of every 2nd trace point to the spline, searching near the matching arc position
        idx = np.arange(0, n, 2)
        rel = ((idx - s_first) % n) * (m["L"] / n) / m["h"]
        j0 = np.round(rel).astype(int)
        win = np.arange(-40, 41)
        J = (j0[:, None] + win[None, :]) % Ns
        dd = np.hypot(C[J][:, :, 0] - D[idx][:, None, 0], C[J][:, :, 1] - D[idx][:, None, 1]).min(1)
        if dd.max() < tol or len(ctrl) > 400:
            break
        added = 0
        taken = []
        for c in np.argsort(-dd):
            if dd[c] < tol or added >= 12:
                break
            s_new = int(idx[c])
            near_existing = min(min(abs(s_new - q), n - abs(s_new - q)) for q in ctrl) < min_gap
            near_new = any(min(abs(s_new - q), n - abs(s_new - q)) < 60 for q in taken)
            if near_existing or near_new:
                continue
            ctrl.append(s_new)
            taken.append(s_new)
            added += 1
        if not added:
            break
    return pts, m, float(dd.max()), float(dd.mean())


# ---------------------------------------------------------------- banking
def oval_sections(m, pit_pts, n_turns):
    """Split an oval into its n_turns banked turns and the straights between (tri-ovals and doglegs count as straight)."""
    X, Y, h, N = np.array(m["x"]), np.array(m["y"]), m["h"], m["N"]
    k = curvature(X, Y, h, 20)
    ak = np.abs(k)
    kmax = np.percentile(ak, 98)
    import layout_core as lc
    # clearly curving stretches; the n_turns that turn furthest are the banked turns
    cores = lc.runs((ak > 0.5 * kmax).astype(int).tolist())
    angle = lambda r: abs(np.sum(k[(r[0] + np.arange(r[1])) % N]) * h)
    turns = sorted(sorted(cores, key=angle, reverse=True)[:n_turns], key=lambda r: r[0])
    straights = []
    if turns:
        tf = np.zeros(N, int)
        for a, ln in turns:
            tf[(a + np.arange(ln)) % N] = 1
        straights = lc.runs((1 - tf).tolist())
    front = None
    if straights:
        if pit_pts is not None and len(pit_pts):
            def gap(st):
                a, ln = st
                ids = (a + np.arange(0, ln, 5)) % N
                P = np.column_stack([X[ids], Y[ids]])
                return np.min(np.hypot(P[:, None, 0] - pit_pts[None, :, 0], P[:, None, 1] - pit_pts[None, :, 1]))
            front = min(straights, key=gap)
        else:
            front = max(straights, key=lambda st: st[1])
    return turns, straights, front


def bank_profile(m, turns, front, spec, sf_index, notes):
    N, h = m["N"], m["h"]
    tv = spec["turns"]
    # turns in driving order starting after the start line
    order = sorted(turns, key=lambda t: (t[0] - sf_index) % N)
    if isinstance(tv, (int, float)):
        tb = [float(tv)] * len(order)
    elif len(tv) == len(order):
        tb = [float(v) for v in tv]
    else:
        notes.append(f"found {len(order)} turns, spec lists {len(tv)}: using the average banking")
        tb = [float(sum(tv) / len(tv))] * len(order)
    tlen = min(ln for _, ln in order) * h if order else 100
    trans = max(30.0, min(150.0, 0.25 * tlen))
    in_front = np.zeros(N, bool)
    if front:
        in_front[(front[0] + np.arange(front[1])) % N] = True
    bank = np.where(in_front, spec["front"], spec["back"]).astype(float)
    base = bank.copy()
    for (a, ln), b in zip(order, tb):
        idx = (a + np.arange(ln)) % N
        bank[idx] = b
        for side in (-1, 1):
            for dstep in range(1, int(trans / h)):
                j = (a - dstep) % N if side < 0 else (a + ln - 1 + dstep) % N
                t = 1 - dstep * h / trans
                t = t * t * (3 - 2 * t)
                cand = base[j] + t * (b - base[j])
                if abs(cand - base[j]) > abs(bank[j] - base[j]):
                    bank[j] = cand
    return bank, tb


def refine_elevation(lc, pts, m, Z, bank_samples, tol=0.75, max_add=40):
    """Give each control point its height from the target profile Z (one value per sample of spline m), then add
    points wherever the spline's interpolated height misses the profile by more than `tol` metres (a crest or dip
    between two widely spaced points). New points sit on the existing curve, so the shape barely changes."""
    h, N = m["h"], m["N"]
    for p, s_rel in zip(pts, m["ptRel"]):
        p["z"] = round(float(Z[int(round(s_rel / h)) % N]), 2)
    added = 0
    while added < max_add:
        m2 = lc.build_centerline(pts, 0.0)
        jj = np.round(np.arange(m2["N"]) * m2["h"] / h).astype(int) % N
        dev = np.abs(np.array(m2["z"]) - Z[jj])
        if dev.max() < tol:
            break
        rel, L2 = np.array(m2["ptRel"]), m2["L"]
        picks = []
        for c in np.argsort(-dev):
            if dev[c] < tol or len(picks) >= 4:
                break
            s = c * m2["h"]
            if np.min(np.minimum(np.abs(rel - s), L2 - np.abs(rel - s))) < 25:
                continue
            if any(min(abs(s - q), L2 - abs(s - q)) < 80 for _, q in picks):
                continue
            picks.append((c, s))
        if not picks:
            break
        for c, s in sorted(picks, key=lambda q: -q[1]):        # from the end, so earlier indices stay valid
            j = jj[c]
            pts.insert(int(np.searchsorted(rel, s)), dict(
                x=round(float(m2["x"][c]), 1), y=round(float(m2["y"][c]), 1),
                z=round(float(Z[j]), 2), bank=round(float(bank_samples[j]), 1)))
            added += 1
    return pts, lc.build_centerline(pts, 0.0), added


def relax_banks(pts, m, half, rate=0.06):
    """Keep the twist between neighbouring control points gentle: the road edge may climb at most `rate`
    (6 %) relative to the centre. Where it would be steeper, raise the lower-banked point, which spreads the
    transition out instead of taking banking away from the turn. The designer interpolates with a smoothstep,
    whose steepest slope is 1.5x the average, hence the 1.5."""
    n, L, rel = len(pts), m["L"], m["ptRel"]
    b = [math.radians(p["bank"]) for p in pts]
    for _ in range(200):
        moved = False
        for i in range(n):
            j = (i + 1) % n
            d = (rel[j] - rel[i]) % L or L
            lim = rate * d / (1.5 * half)
            si, sj = math.sin(b[i]), math.sin(b[j])
            if abs(sj - si) > lim + 1e-6:
                if si < sj:
                    b[i] = math.asin(max(-1.0, min(1.0, sj - lim)))
                else:
                    b[j] = math.asin(max(-1.0, min(1.0, si - lim)))
                moved = True
        if not moved:
            break
    for p, v in zip(pts, b):
        p["bank"] = round(math.degrees(v), 1)


# ---------------------------------------------------------------- checks
def crossings(X, Y, step=3):
    ids = np.arange(0, len(X), step)
    P = np.column_stack([X[ids], Y[ids]])
    M = len(P)
    cell = 20.0
    grid = defaultdict(list)
    for k in range(M):
        a, b = P[k], P[(k + 1) % M]
        for gx in range(int(math.floor(min(a[0], b[0]) / cell)), int(math.floor(max(a[0], b[0]) / cell)) + 1):
            for gy in range(int(math.floor(min(a[1], b[1]) / cell)), int(math.floor(max(a[1], b[1]) / cell)) + 1):
                grid[(gx, gy)].append(k)

    def inter(a, b, c, d):
        d1 = (d[0] - c[0]) * (a[1] - c[1]) - (d[1] - c[1]) * (a[0] - c[0])
        d2 = (d[0] - c[0]) * (b[1] - c[1]) - (d[1] - c[1]) * (b[0] - c[0])
        d3 = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        d4 = (b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0])
        return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)

    for segs in grid.values():
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i], segs[j]
                if abs(a - b) <= 1 or abs(a - b) >= M - 1:
                    continue
                if inter(P[a], P[(a + 1) % M], P[b], P[(b + 1) % M]):
                    return True
    return False


def worst_gap(X, Y, h, excl_m=80):
    N = len(X)
    cell = 25.0
    grid = defaultdict(list)
    for i in range(0, N, 2):
        grid[(int(X[i] // cell), int(Y[i] // cell))].append(i)
    excl = int(excl_m / h)
    best = math.inf
    for (gx, gy), ids in grid.items():
        near = [j for ox in (-1, 0, 1) for oy in (-1, 0, 1) for j in grid.get((gx + ox, gy + oy), ())]
        for i in ids:
            for j in near:
                di = abs(i - j)
                if min(di, N - di) < excl:
                    continue
                d = math.hypot(X[i] - X[j], Y[i] - Y[j])
                if d < best:
                    best = d
    return best


# ---------------------------------------------------------------- main per-track import
def import_track(t, osm, lc, ovals_done):
    nodes, ways, rels = osm
    notes = []
    proj = Proj(t["lat"], t["lon"])
    target = t["length"]
    cands = []
    for r in rels:
        roles = {mm["ref"]: mm.get("role", "") for mm in r["members"] if mm["type"] == "way"}
        # a circuit relation is curated: trust its roles for the pit lane rather than guessing from street names
        mem = [mm["ref"] for mm in r["members"]
               if mm["type"] == "way" and mm["ref"] in ways and "pit" not in mm.get("role", "").lower()
               and ways[mm["ref"]]["tags"].get("surface") not in BAD_SURFACE]
        sf_nodes = [mm["ref"] for mm in r["members"] if mm["type"] == "node" and mm["ref"] in nodes
                    and re.search(r"start|finish", mm.get("role", ""), re.I)]
        if mem:
            cands.append((f"relation {r['id']} ({r['tags'].get('name', '?')})", mem, True, roles, sf_nodes))
    def racing_way(tags):
        return tags.get("highway") == "raceway" or (tags.get("leisure") == "track" and re.search(
            r"motor|racing", tags.get("sport", "")))
    race = [w for w, wd in ways.items() if racing_way(wd["tags"]) and not excluded(wd["tags"])
            and not is_pit(wd["tags"])]
    if race:
        cands.append(("raceway network", race, False, {}, []))
    best = None
    for label, way_ids, is_rel, roles, sf_nodes in cands:
        # relations sometimes miss one member (a short link street): allow bigger gaps to be joined there
        edges = build_graph(way_ids, ways, nodes, proj, heal=25.0 if is_rel else 12.0)
        options = []
        tol = t.get("tol", 0.08)
        if is_rel:
            eu = euler_loop(edges, roles)
            if eu and abs(eu[1] - target) / target <= tol:
                options.append(((abs(eu[1] - target) / target, eu[0], eu[1]), eu[2]))
        loops, capped = best_cycle(edges, target, tol=tol)
        if capped:
            notes.append(f"loop search capped for {label}")
        options += [(c, False) for c in loops]
        for cand, directed in options:
            score = rank_loop(cand, edges, ways, t["kind"], is_rel) - (0.005 if directed else 0.0)
            if math.isinf(score):
                continue
            if best is None or score < best[0]:
                best = (score, label, edges, cand, directed, sf_nodes)
    if best is None:
        return None, ["no loop within 8% of the official length in OpenStreetMap"]
    _, label, edges, (sc, cyc, ln), rel_directed, sf_nodes = best
    P, segs = cycle_polyline(edges, cyc)
    # which stretches are in tunnels or on bridges (one flag per polyline segment)
    vflag = np.zeros(len(P), bool)
    for k, fwd, start in segs:
        if edges[k]["way"] is not None and covered(ways[edges[k]["way"]]["tags"]):
            vflag[start:start + len(edges[k]["pts"]) - 1] = True
    if t.get("scale_to_length"):
        c = P.mean(axis=0)
        P = c + (P - c) * (target / ln)
        notes.append(f"OSM trace was {ln:.0f} m: scaled by {target / ln:.2f} to the official length")

    # ---- direction: oneway race tags if they cover enough of the loop, else catalogue ----
    agree = against = 0.0
    for k, fwd, _ in segs:
        if edges[k]["way"] is None:                   # a healed gap
            continue
        tags = ways[edges[k]["way"]]["tags"]
        if tags.get("highway") != "raceway" or tags.get("oneway") not in ("yes", "-1"):
            continue
        way_fwd = tags["oneway"] == "yes"
        if fwd == way_fwd:
            agree += edges[k]["length"]
        else:
            against += edges[k]["length"]
    want_cw = t["direction"] == "cw"
    if rel_directed:
        osm_cw = signed_area(P) < 0
        dir_src = "OSM circuit relation"
        if osm_cw != want_cw:
            notes.append(f"OSM says {'clockwise' if osm_cw else 'anticlockwise'}, catalogue says {t['direction']}: using OSM")
    elif agree + against > 0.3 * ln and max(agree, against) > 0.8 * (agree + against):
        if against > agree:
            P = P[::-1]
            vflag = np.roll(vflag[::-1], -1)          # segment i now runs between the reversed vertices
        osm_cw = signed_area(P) < 0
        dir_src = "OSM oneway"
        if osm_cw != want_cw:
            notes.append(f"OSM says {'clockwise' if osm_cw else 'anticlockwise'}, catalogue says {t['direction']}: using OSM")
    else:
        if (signed_area(P) < 0) != want_cw:
            P = P[::-1]
            vflag = np.roll(vflag[::-1], -1)
        dir_src = "catalogue"

    # ---- pit lane points (for start line and pit side) ----
    pit_pts = []
    pit_way_ids = {mm["ref"] for r in rels for mm in r["members"]
                   if mm["type"] == "way" and mm["ref"] in ways and is_pit(ways[mm["ref"]]["tags"], mm.get("role", ""))}
    pit_way_ids |= {w for w, wd in ways.items() if is_pit(wd["tags"]) and wd["tags"].get("highway") in ("raceway", "service")}
    for w in pit_way_ids:
        q = np.array([proj(nodes[n]) for n in ways[w]["nodes"] if n in nodes])
        if len(q) >= 2:
            dq, _ = densify(q, 5.0) if len(q) > 2 else (q, 0)
            pit_pts.append(dq)
    pit_pts = np.vstack(pit_pts) if pit_pts else np.zeros((0, 2))

    D, L_osm, dflag = densify(P, 1.0, vflag)
    sigma = min(25.0, L_osm / 120.0) if t["kind"] == "oval" else 4.0
    D = smooth_loop(D, sigma)
    # OSM often draws street corners as sharp right angles: round off anything tighter than a realistic minimum
    r_min = {"street": 10.0, "road": 12.0, "oval": 40.0}[t["kind"]]
    for _ in range(10):
        kk = np.abs(curvature(D[:, 0], D[:, 1], 1.0, 3))
        bad = kk > 1.0 / r_min
        if not bad.any():
            break
        grow = np.convolve(np.concatenate([bad[-30:], bad, bad[:30]]).astype(float), np.ones(61), "same")[30:-30] > 0
        Ds = smooth_loop(D, 5.0)
        D[grow] = Ds[grow]
    n = len(D)
    # keep only pit points that run alongside the loop (within 60 m)
    if len(pit_pts):
        dmin = np.array([np.min(np.hypot(D[::4, 0] - p[0], D[::4, 1] - p[1])) for p in pit_pts])
        pit_pts = pit_pts[(dmin < 60) & (dmin > 2)]

    # ---- start line (road/street): middle of the stretch the pit lane runs beside ----
    def nearest_idx(p):
        return int(np.argmin(np.hypot(D[:, 0] - p[0], D[:, 1] - p[1])))

    sf_src = "pit lane"
    if sf_nodes:                                            # the relation marks the real start/finish line
        sf_idx = nearest_idx(proj(nodes[sf_nodes[0]]))
        sf_src = "OSM start/finish node"
    elif len(pit_pts) >= 4:
        proj_s = np.array(sorted({nearest_idx(p) for p in pit_pts}))
        gaps = np.diff(np.concatenate([proj_s, [proj_s[0] + n]]))
        g = int(np.argmax(gaps))
        start, end = proj_s[(g + 1) % len(proj_s)], proj_s[g]
        span = (end - start) % n
        sf_idx = int(start + span / 2) % n
    else:
        k = curvature(D[:, 0], D[:, 1], 1.0, 15)
        straight = (np.abs(k) < 1 / 800).astype(int).tolist()
        runs = lc.runs(straight)
        a, ln = max(runs, key=lambda r: r[1]) if runs else (0, 0)
        sf_idx = int(a + ln / 2) % n
        sf_src = "longest straight"
        notes.append("no pit lane in OSM: start line on the longest straight, pit side automatic")

    fit = fit_points(lc, D, t["kind"], sf_idx)

    def tightest(f):
        return 1.0 / max(np.abs(curvature(np.array(f[1]["x"]), np.array(f[1]["y"]), f[1]["h"], 4)).max(), 1e-9)

    # The fitted curve can pinch tighter than the trace: smooth the trace at those spots and refit, keeping
    # whichever fit has the gentlest tightest corner (smoothing a hairpin between close parallel legs can make
    # it worse, so never assume the last attempt is the best).
    best_fit = (tightest(fit), fit)
    for attempt in range(6):
        m = fit[1]
        kk = np.abs(curvature(np.array(m["x"]), np.array(m["y"]), m["h"], 4))
        tight = np.nonzero(kk > 1.0 / (0.95 * r_min))[0]
        if not len(tight):
            break
        mask = np.zeros(n, bool)
        for j in tight:
            c = int(round(sf_idx + j * m["h"] * n / m["L"])) % n
            mask[(c + np.arange(-35, 36)) % n] = True
        Ds = smooth_loop(D, 5.0 + 1.5 * attempt)          # a little stronger each round
        D[mask] = Ds[mask]
        fit = fit_points(lc, D, t["kind"], sf_idx)
        if tightest(fit) > best_fit[0]:
            best_fit = (tightest(fit), fit)
    pts, m, dev_max, dev_mean = best_fit[1]
    X, Y = np.array(m["x"]), np.array(m["y"])

    # ---- ovals: sections, start line, banking ----
    bank_samples = np.zeros(m["N"])
    sf_spline = 0
    if t["kind"] == "oval":
        spec = t["banking"]
        n_turns = spec.get("nturns") or (len(spec["turns"]) if isinstance(spec["turns"], list) else 2)
        turns, straights, front = oval_sections(m, pit_pts if len(pit_pts) else None, n_turns)
        if front and not sf_nodes:
            sf_spline = (front[0] + front[1] // 2) % m["N"]
            sf_src = "middle of front straight"
        if t.get("sf_shift") and not sf_nodes:
            sf_spline = (sf_spline + int(round(t["sf_shift"] / m["h"]))) % m["N"]
            sf_src += f" + {t['sf_shift']:.0f} m"
        bank_samples, tb = bank_profile(m, turns, front, t["banking"], sf_spline, notes)
        notes.append(f"{len(turns)} turns banked {', '.join(f'{b:g}' for b in tb)}; front {t['banking']['front']:g}, "
                     f"others {t['banking']['back']:g}")
    elif t.get("bank_from"):
        src = ovals_done.get(t["bank_from"])
        if src is None:
            notes.append(f"{t['bank_from']} not imported: no banking copied")
        else:
            SX, SY, SB = src
            for j in range(0, m["N"]):
                dd = np.hypot(SX - X[j], SY - Y[j])
                q = int(np.argmin(dd))
                bank_samples[j] = SB[q] if dd[q] < 6.0 else 0.0
            on = np.mean(bank_samples > 0.5)
            notes.append(f"banking copied from {t['bank_from']} on {on * 100:.0f}% of the lap")
    for p, s_rel in zip(pts, m["ptRel"]):
        j = int(round(s_rel / m["h"])) % m["N"]
        p["bank"] = round(float(bank_samples[j]), 1)
        p["x"], p["y"] = round(p["x"], 1), round(p["y"], 1)
    relax_banks(pts, m, float(t.get("width", DEFAULT_WIDTH[t["kind"]])) / 2, rate=0.04 if t["kind"] == "oval" else 0.06)

    if t["kind"] != "oval":
        # start line from the pit lane: control point 0 sits at sf_idx, so it's at the start of the spline
        sf_spline = 0
    start_pos = (sf_spline * m["h"]) / m["L"]

    # ---- settings ----
    width = float(t.get("width", DEFAULT_WIDTH[t["kind"]]))
    # the series' usual field, but no more than suits the lap (tiny ovals would be lined with pit boxes)
    pits = min(max(SERIES_PITS[s] for s in t["series"]), max(10, int(m["L"] / 15)))
    pit_side = "auto"
    if len(pit_pts) >= 4:
        j = int(round(sf_spline)) % m["N"]
        a, b = (j - 3) % m["N"], (j + 3) % m["N"]
        fx, fy = X[b] - X[a], Y[b] - Y[a]
        near = pit_pts[np.argsort(np.hypot(pit_pts[:, 0] - X[j], pit_pts[:, 1] - Y[j]))[:20]]
        cross = fx * (near[:, 1] - Y[j]) - fy * (near[:, 0] - X[j])          # > 0: pit lane on the left
        pit_side = "left" if np.mean(cross) > 0 else "right"
    if t["kind"] == "oval":
        st = dict(roadWidth=width, runoff=1.5, runoffIn=40, kerbs=False, gravel=False)
    elif t["kind"] == "street":
        st = dict(roadWidth=width, runoff=2.5, runoffIn=2.5, kerbs=True, gravel=False)
    elif t.get("bank_from"):
        st = dict(roadWidth=width, runoff=3, runoffIn=12, kerbs=True, gravel=False)
    else:
        st = dict(roadWidth=width, runoff=15, runoffIn=15, kerbs=True, gravel=True)
    st.update(pitBoxes=pits, pitSide=pit_side, startPos=round(start_pos, 5))

    # ---- checks: crossings, sections too close, hairpins too tight ----
    if crossings(X, Y):
        return None, notes + ["the layout crosses itself (needs a bridge), skipped"]
    gap = worst_gap(X, Y, m["h"])
    if gap < 3.0:          # two passes through the same junction: a flat crossing the builder can't make
        return None, notes + [f"the layout passes through the same spot twice ({gap:.1f} m apart), skipped"]
    doc = dict(name=t["name"], settings=st, points=[dict(x=p["x"], y=p["y"], z=0, bank=p["bank"]) for p in pts])
    model = lc.compute(doc)
    min_r = model["stats"]["minRadius"]
    w_ok = min(width, gap - 3.0, 2 * (min_r - 2.5))
    if w_ok < width - 0.25:
        new_w = max(8.0, math.floor(w_ok * 2) / 2)
        notes.append(f"road narrowed from {width:g} to {new_w:g} m (closest sections {gap:.0f} m apart, "
                     f"tightest radius {min_r:.0f} m)")
        st["roadWidth"] = new_w
        if gap - 2 < new_w or min_r < new_w / 2 + 2:
            notes.append("still tight after narrowing: check this layout in the designer")

    # ---- elevation: terrain under the track, plus the rise of banked turns above the ground they sit on ----
    half = st["roadWidth"] / 2
    flag_spl = np.array([dflag[int(round(sf_idx + j * m["h"] * n / m["L"])) % n] for j in range(m["N"])])
    G = ground_profile(t, m, proj, flag_spl, bank_samples, half, ELEV_CACHE, notes)
    Z = G + half * np.sin(np.radians(bank_samples))
    sf_xy = (X[sf_spline], Y[sf_spline])
    pts, m2, added = refine_elevation(lc, pts, m, Z, bank_samples)
    relax_banks(pts, m2, half, rate=0.04 if t["kind"] == "oval" else 0.06)   # ovals: longer, gentler spirals
    if added:
        notes.append(f"{added} points added to follow the hills")
    if t["kind"] == "oval":
        j2 = int(np.argmin(np.hypot(np.array(m2["x"]) - sf_xy[0], np.array(m2["y"]) - sf_xy[1])))
        st["startPos"] = round(j2 * m2["h"] / m2["L"], 5)
    z2 = np.array(m2["z"])
    gw = max(2, int(round(10 / m2["h"])))
    grade = np.abs(np.roll(z2, -gw) - np.roll(z2, gw)) / (2 * gw * m2["h"]) * 100
    climb = float(z2.max() - z2.min())

    entry = dict(id=t["id"], name=t["name"], config=t["config"], series=t["series"], kind=t["kind"],
                 length=round(t["length"]), fitted=round(m2["L"]), settings=st,
                 points=[[p["x"], p["y"], p["z"], p["bank"]] for p in pts],
                 source=f"© OpenStreetMap contributors: {label}; elevation: OpenTopoData (NED / EU-DEM / SRTM)")
    info = dict(label=label, len_osm=ln, dev_max=dev_max, dev_mean=dev_mean, dir_src=dir_src, sf_src=sf_src,
                pit_side=pit_side, npts=len(pts), climb=climb, grade=float(grade.max()))
    if t["kind"] == "oval":
        ovals_done[t["id"]] = (X, Y, bank_samples)
    return (entry, info), notes


def contact_sheet(entries, lc, path):
    cells = []
    for e, info, notes in entries:
        doc = dict(name=e["name"], settings=e["settings"],
                   points=[dict(x=p[0], y=p[1], z=p[2], bank=p[3]) for p in e["points"]])
        lay = lc.layout_from_doc(doc)
        S = np.array(lay["samples"])
        X, Y = S[:, 0], S[:, 1]
        pad = 40
        x0, x1, y0, y1 = X.min() - pad, X.max() + pad, Y.min() - pad, Y.max() + pad
        poly = " ".join(f"{x:.0f},{-y:.0f}" for x, y in zip(X[::4], Y[::4]))
        banked = S[:, 3]
        bpoly = ""
        for k in range(0, len(S) - 4, 4):
            if abs(banked[k]) > 3:
                bpoly += f'<line x1="{X[k]:.0f}" y1="{-Y[k]:.0f}" x2="{X[k + 4]:.0f}" y2="{-Y[k + 4]:.0f}"/>'
        # direction arrow ~ 3 % into the lap, start line at sample 0
        a = int(len(S) * 0.03)
        fx, fy = X[a + 5] - X[a], Y[a + 5] - Y[a]
        ang = math.degrees(math.atan2(-fy, fx))
        size = max(x1 - x0, y1 - y0)
        pit = "L" if e["settings"]["pitSide"] == "left" else ("R" if e["settings"]["pitSide"] == "right" else "?")
        cells.append(
            f'<figure><svg viewBox="{x0:.0f} {-y1:.0f} {x1 - x0:.0f} {y1 - y0:.0f}">'
            f'<polyline points="{poly}" fill="none" stroke="#333" stroke-width="{size / 90:.1f}" stroke-linejoin="round"/>'
            f'<g stroke="#e8590c" stroke-width="{size / 90:.1f}">{bpoly}</g>'
            f'<circle cx="{X[0]:.0f}" cy="{-Y[0]:.0f}" r="{size / 40:.0f}" fill="#d00"/>'
            f'<g transform="translate({X[a]:.0f},{-Y[a]:.0f}) rotate({ang:.0f})"><path d="M{-size / 25:.0f},{-size / 40:.0f} L0,0 L{-size / 25:.0f},{size / 40:.0f}" '
            f'fill="none" stroke="#1971c2" stroke-width="{size / 120:.1f}"/></g></svg>'
            f'<figcaption><b>{html.escape(e["name"])}</b><br>{html.escape(e["config"])} · {e["fitted"] / 1000:.2f} km '
            f'({(e["fitted"] / e["length"] - 1) * 100:+.1f}%) · pit {pit} · {len(e["points"])} pts</figcaption></figure>')
    page = ("<!doctype html><meta charset=utf-8><title>Track contact sheet</title><style>"
            "body{font:12px system-ui;margin:12px;background:#fff}main{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}"
            "figure{margin:0;border:1px solid #ddd;border-radius:6px;padding:6px}svg{width:100%;aspect-ratio:1;display:block}"
            "figcaption{margin-top:4px;line-height:1.3}</style><main>" + "".join(cells) + "</main>")
    open(path, "w", encoding="utf-8").write(page)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")      # circuit names come in many scripts
    args = [a for a in sys.argv[1:] if not a.startswith("--only")]
    only = set()
    for a in sys.argv[1:]:
        if a.startswith("--only"):
            only = set(a.split("=", 1)[1].split(","))
    cache, builder, lib_path, report_path = args[:4]
    sheet = args[4] if len(args) > 4 else None
    global ELEV_CACHE
    ELEV_CACHE = os.path.join(cache, "elevation_cache.json")
    sys.path.insert(0, builder)
    import layout_core as lc
    # ovals first so road courses can borrow their banking
    tracks = sorted(TRACKS, key=lambda t: 0 if t["kind"] == "oval" else 1)
    ovals_done, out, report, sheet_rows = {}, [], [], []
    for t in tracks:
        if only and t["id"] not in only and not (t["kind"] == "oval" and any(
                x.get("bank_from") == t["id"] for x in TRACKS if x["id"] in only)):
            continue
        path = os.path.join(cache, cache_name(t))
        if not os.path.exists(path):
            report.append(f"MISSING  {t['id']}: no cached OSM data")
            continue
        try:
            res, notes = import_track(t, load_osm(path), lc, ovals_done)
        except Exception as ex:                      # keep going; report the failure
            import traceback
            res, notes = None, [f"error: {type(ex).__name__}: {ex}", traceback.format_exc(limit=3)]
        if res is None:
            report.append(f"FAILED   {t['id']}: " + "; ".join(notes))
            continue
        entry, info = res
        out.append(entry)
        sheet_rows.append((entry, info, notes))
        report.append(f"OK       {t['id']}: {entry['fitted']:.0f} m vs {entry['length']:.0f} m "
                      f"({(entry['fitted'] / entry['length'] - 1) * 100:+.1f}%), {info['npts']} pts, dev max "
                      f"{info['dev_max']:.2f} m; climb {info['climb']:.0f} m, steepest {info['grade']:.0f}%; "
                      f"{info['label']}; direction {info['dir_src']}; start {info['sf_src']}; "
                      f"pits {info['pit_side']}" + ("".join(f"\n           - {n}" for n in notes)))
        print(report[-1].splitlines()[0], flush=True)
    order = {t["id"]: k for k, t in enumerate(TRACKS)}
    out.sort(key=lambda e: order[e["id"]])
    json.dump(out, open(lib_path, "w", encoding="utf-8"), separators=(",", ":"))
    open(report_path, "w", encoding="utf-8").write("\n".join(report) + "\n")
    if sheet:
        sheet_rows.sort(key=lambda r: order[r[0]["id"]])
        contact_sheet(sheet_rows, lc, sheet)
    print(f"{len(out)} tracks imported, {sum(1 for r in report if not r.startswith('OK'))} not", flush=True)


if __name__ == "__main__":
    main()
