"""Layout maths shared with designer/track-designer.html.

The designer exports fully sampled layouts, so the builder normally just reads them.
This module rebuilds the same samples from the control points alone, which lets the
builder accept hand-written or points-only layout files. Keep it in sync with the
`buildCenterline` and `compute` functions in the designer.

Runs on plain Python 3 (no Blender needed):
    python layout_core.py some.layout.json    -> prints the stats
"""
import collections
import json
import math
import re
import sys
import unicodedata

KERB_W = 1.2        # kerb strip width (m)
APRON_W = 14.0      # pit apron width (m)
KERB_R = 120.0      # corners tighter than this get kerbs (m)
GRAVEL_R = 110.0    # corners tighter than this get gravel on the outside (m)
SPACING = 1.0       # centerline sample spacing (m)

# planWidth: road width measured from above, so banked sections get a wider tilted surface (see build_track.Track)
# bankSmooth*: optional smoothing of the banking along the lap (see smooth_banking)
DEFAULTS = dict(roadWidth=12.0, runoff=15.0, runoffIn=15.0, kerbs=True, gravel=True, pitBoxes=12, pitSide="auto", startPos=0.08,
                planWidth=True, bankSmooth=False, bankSmoothMode="avg", bankSmoothLen=100.0)


MAX_PITS = 60


def pit_plan(n):
    """Big fields (over 24 cars) get two rows of pit boxes and a tighter grid, so the pit area stays a sensible length.
    Two-row aprons get 20% spare length for spots where the apron is too narrow for two cars side by side."""
    rows = 2 if n > 24 else 1
    return dict(rows=rows, perRow=math.ceil(n / 2 * 1.2) if rows == 2 else n, gridGap=5 if n > 24 else 8)


def norm_settings(s):
    """Fill in defaults; layouts saved before the infield run-off setting existed use the same run-off on both sides."""
    s = s or {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in s.items() if k in DEFAULTS})
    if "runoffIn" not in s:
        out["runoffIn"] = out["runoff"]
    return out

FLAG_KERB = (1, 2)      # (left, right)
FLAG_GRAVEL = (4, 8)
FLAG_PIT = (16, 32)


def slugify(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    s = re.sub(r"[\s-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s).strip("_")
    return s or "my_track"


def _cr(t0, t1, t2, t3, u, v0, v1, v2, v3):
    a1 = ((t1 - u) * v0 + (u - t0) * v1) / (t1 - t0)
    a2 = ((t2 - u) * v1 + (u - t1) * v2) / (t2 - t1)
    a3 = ((t3 - u) * v2 + (u - t2) * v3) / (t3 - t2)
    b1 = ((t2 - u) * a1 + (u - t0) * a2) / (t2 - t0)
    b2 = ((t3 - u) * a2 + (u - t1) * a3) / (t3 - t1)
    return ((t2 - u) * b1 + (u - t1) * b2) / (t2 - t1)


def build_centerline(pts, start_frac):
    """Closed centripetal Catmull-Rom through the control points, resampled every ~1 m from the start line."""
    n = len(pts)
    # banking is "outside of the turn goes up"; on a straight it tilts toward the infield like the turns around it
    area2 = sum(pts[i]["x"] * pts[(i + 1) % n]["y"] - pts[(i + 1) % n]["x"] * pts[i]["y"] for i in range(n))
    roll = []
    for i, p in enumerate(pts):
        a, b = pts[(i - 1) % n], pts[(i + 1) % n]
        ux, uy, vx, vy = p["x"] - a["x"], p["y"] - a["y"], b["x"] - p["x"], b["y"] - p["y"]
        cr = ux * vy - uy * vx
        sin_turn = cr / ((math.hypot(ux, uy) * math.hypot(vx, vy)) or 1.0)
        turns_left = area2 > 0 if abs(sin_turn) < 0.02 else cr > 0
        roll.append((p.get("bank") or 0) * (-1 if turns_left else 1))
    rx, ry, rz, rr, rs, rseg = [], [], [], [], [], []
    pt_s = [0.0] * n
    acc, px, py = 0.0, None, None
    for i in range(n):
        p0, p1, p2, p3 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        d01 = max(1e-3, math.sqrt(math.hypot(p1["x"] - p0["x"], p1["y"] - p0["y"])))
        d12 = max(1e-3, math.sqrt(math.hypot(p2["x"] - p1["x"], p2["y"] - p1["y"])))
        d23 = max(1e-3, math.sqrt(math.hypot(p3["x"] - p2["x"], p3["y"] - p2["y"])))
        t0, t1 = 0.0, d01
        t2 = t1 + d12
        t3 = t2 + d23
        seg_len = math.hypot(p2["x"] - p1["x"], p2["y"] - p1["y"])
        steps = max(6, math.ceil(seg_len / 0.5))
        zs = [q.get("z") or 0 for q in (p0, p1, p2, p3)]
        for k in range(steps):
            t = k / steps
            u = t1 + (t2 - t1) * t
            x = _cr(t0, t1, t2, t3, u, p0["x"], p1["x"], p2["x"], p3["x"])
            y = _cr(t0, t1, t2, t3, u, p0["y"], p1["y"], p2["y"], p3["y"])
            z = _cr(t0, t1, t2, t3, u, *zs)
            e = t * t * (3 - 2 * t)
            if px is not None:
                acc += math.hypot(x - px, y - py)
            if k == 0:
                pt_s[i] = acc
            rx.append(x); ry.append(y); rz.append(z)
            rr.append(roll[i] + (roll[(i + 1) % n] - roll[i]) * e)
            rs.append(acc); rseg.append(i)
            px, py = x, y
    L = acc + math.hypot(rx[0] - px, ry[0] - py)
    rx.append(rx[0]); ry.append(ry[0]); rz.append(rz[0]); rr.append(rr[0]); rs.append(L); rseg.append(n - 1)

    N = max(40, round(L / SPACING))
    h = L / N
    s0 = (start_frac % 1.0) * L
    x, y, z, rl, seg = [0.0] * N, [0.0] * N, [0.0] * N, [0.0] * N, [0] * N
    for j in range(N):
        s = (s0 + j * h) % L
        lo, hi = 0, len(rs) - 1
        while hi - lo > 1:
            mid = (lo + hi) >> 1
            if rs[mid] <= s:
                lo = mid
            else:
                hi = mid
        span = (rs[hi] - rs[lo]) or 1.0
        f = (s - rs[lo]) / span
        x[j] = rx[lo] + (rx[hi] - rx[lo]) * f
        y[j] = ry[lo] + (ry[hi] - ry[lo]) * f
        z[j] = rz[lo] + (rz[hi] - rz[lo]) * f
        rl[j] = rr[lo] + (rr[hi] - rr[lo]) * f
        seg[j] = rseg[lo]
    pt_rel = [((s - s0) % L + L) % L for s in pt_s]
    return dict(N=N, h=h, L=L, x=x, y=y, z=z, roll=rl, seg=seg, ptRel=pt_rel)


def _wrap(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def moving_min(a, w):
    n = len(a)
    return [min(a[(i + k) % n] for k in range(-w, w + 1)) for i in range(n)]


def moving_avg(a, w):
    n = len(a)
    return [sum(a[(i + k) % n] for k in range(-w, w + 1)) / (2 * w + 1) for i in range(n)]


def dilate(a, before, after):
    n = len(a)
    out = [0] * n
    for i in range(n):
        if a[i]:
            for k in range(-before, after + 1):
                out[(i + k) % n] = 1
    return out


def box_circ(a, r):
    """Running-sum average over ±r samples round the lap."""
    n, w = len(a), 2 * r + 1
    s = sum(a[k % n] for k in range(-r, r + 1))
    out = [0.0] * n
    for i in range(n):
        out[i] = s / w
        s += a[(i + r + 1) % n] - a[(i - r) % n]
    return out


def extreme_circ(a, r, use_max):
    """Highest (or lowest) value within ±r samples round the lap, with a sliding-window queue."""
    n = len(a)
    out, q = [0.0] * n, collections.deque()
    for k in range(-r, n + r):
        v = a[k % n]
        while q and (v >= a[q[-1] % n] if use_max else v <= a[q[-1] % n]):
            q.pop()
        q.append(k)
        i = k - r
        if i >= 0:
            while q[0] < i - r:
                q.popleft()
            out[i] = a[q[0] % n]
    return out


def smooth_banking(roll, h, S):
    """Port of the designer's smoothBanking(): 'avg' blends with the neighbours, 'high' spreads the steepest angle
    outward first (no point loses banking), 'low' spreads the flattest first (no point gains any). Left- and
    right-leaning banking are smoothed separately so 'high'/'low' compare angles, not signed rolls."""
    n = len(roll)
    R = min((n - 1) // 2, math.floor(S["bankSmoothLen"] / 2 / h + 0.5))      # Math.round, as in the designer
    if not S["bankSmooth"] or R < 2:
        return roll
    r = R // 2

    def side(sign):
        a = [max(0.0, sign * v) for v in roll]
        if S["bankSmoothMode"] == "high":
            # spreading the steepest angle stops where the road leans the other way, so S-bends don't flip direction
            a = [0.0 if sign * rv < 0 else v for v, rv in zip(extreme_circ(a, R, True), roll)]
        elif S["bankSmoothMode"] == "low":
            a = extreme_circ(a, R, False)
        return box_circ(box_circ(a, r), r)

    up, down = side(1.0), side(-1.0)
    return [u - d for u, d in zip(up, down)]


def runs(a):
    """Circular runs of truthy values as (start, length)."""
    n = len(a)
    z0 = next((i for i in range(n) if not a[i]), -1)
    if z0 < 0:
        return [(0, n)]
    out, start = [], -1
    for k in range(1, n + 1):
        i = (z0 + k) % n
        if a[i] and start < 0:
            start = i
        if not a[i] and start >= 0:
            out.append((start, (i - start) % n))
            start = -1
    return out


def remove_short(a, min_len):
    n = len(a)
    for s, ln in runs(a):
        if ln < min_len and ln < n:
            for k in range(ln):
                a[(s + k) % n] = 0
    return a


def compute(doc):
    """Port of the designer's compute(): returns the sampled model with corridor, flags and spawn points."""
    S = norm_settings(doc.get("settings"))
    pts = doc["points"]
    if len(pts) < 3:
        raise ValueError("a layout needs at least 3 points")
    m = build_centerline(pts, S["startPos"])
    m["roll"] = smooth_banking(m["roll"], m["h"], S)
    N, h, x, y, z = m["N"], m["h"], m["x"], m["y"], m["z"]
    nx, ny, hd, kap = [0.0] * N, [0.0] * N, [0.0] * N, [0.0] * N
    for i in range(N):
        a, b = (i - 1) % N, (i + 1) % N
        tx, ty = x[b] - x[a], y[b] - y[a]
        ln = math.hypot(tx, ty) or 1.0
        nx[i], ny[i] = -ty / ln, tx / ln
        hd[i] = math.atan2(y[b] - y[i], x[b] - x[i])
    kw = max(2, round(4 / h))
    for i in range(N):
        kap[i] = _wrap(hd[(i + kw) % N] - hd[(i - kw) % N]) / (2 * kw * h)

    min_r = min(1 / max(abs(k), 1e-9) for k in kap)
    gw = max(2, round(10 / h))
    max_g = max(abs(z[(i + gw) % N] - z[(i - gw) % N]) / (2 * gw * h) for i in range(N))
    area = sum(x[i] * y[(i + 1) % N] - x[(i + 1) % N] * y[i] for i in range(N))
    direction = "clockwise" if area < 0 else "anticlockwise"
    thr = 1 / 600
    flag = [1 if k > thr else -1 if k < -thr else 0 for k in kap]
    i0 = next((i for i in range(N) if flag[i] == 0), 0)
    corners, cur, turn = 0, 0, 0.0
    for k in range(1, N + 1):
        i = (i0 + k) % N
        if flag[i] != cur:
            if cur != 0 and abs(turn) > 0.35:
                corners += 1
            cur, turn = flag[i], 0.0
        if cur != 0:
            turn += kap[i] * h
    if cur != 0 and abs(turn) > 0.35:
        corners += 1

    # ---- corridor ----
    half = S["roadWidth"] / 2
    infield = 1 if direction == "clockwise" else 0
    d_des = [half + KERB_W + (S["runoffIn"] if si == infield else S["runoff"]) for si in (0, 1)]
    d_min = half + KERB_W + 1.5
    pit_want = half + APRON_W + 3
    pit_si = 0 if S["pitSide"] == "left" else 1 if S["pitSide"] == "right" else 1 - infield
    plan = pit_plan(S["pitBoxes"])
    pit_back, pit_fwd = 25 + plan["perRow"] * 10, 25
    in_pit = [1 if (i * h <= pit_fwd or i * h >= m["L"] - pit_back) else 0 for i in range(N)]
    max_want = max(d_des[0], d_des[1], pit_want)
    want = [[(max(d_des[si], pit_want) if (si == pit_si and in_pit[i]) else d_des[si]) for i in range(N)] for si in (0, 1)]
    inner_raw = [[math.inf] * N, [math.inf] * N]
    for i in range(N):
        r = 0.8 / max(abs(kap[i]), 1e-9)
        inner_raw[0 if kap[i] > 0 else 1][i] = r
    inner = [moving_min(inner_raw[0], round(15 / h)), moving_min(inner_raw[1], round(15 / h))]
    prox = [[math.inf] * N, [math.inf] * N]
    Q = 2 * max_want + 2
    C = max(10.0, Q / 2)
    cr = math.ceil(Q / C)
    cells = {}
    for i in range(N):
        cells.setdefault((math.floor(x[i] / C), math.floor(y[i] / C)), []).append(i)
    excl = round(max(60, 2.5 * max_want) / h)
    for i in range(N):
        gx, gy = math.floor(x[i] / C), math.floor(y[i] / C)
        for ox in range(-cr, cr + 1):
            for oy in range(-cr, cr + 1):
                for j in cells.get((gx + ox, gy + oy), ()):
                    di = abs(i - j)
                    if min(di, N - di) < excl:
                        continue
                    dx, dy = x[j] - x[i], y[j] - y[i]
                    d2 = dx * dx + dy * dy
                    if d2 > Q * Q:
                        continue
                    si = 0 if dx * nx[i] + dy * ny[i] > 0 else 1
                    lim = math.sqrt(d2) / 2 - 0.5
                    if lim < prox[si][i]:
                        prox[si][i] = lim
    w2 = round(12 / h)
    D = []
    for si in (0, 1):
        a = [max(d_min, min(want[si][i], inner[si][i], prox[si][i])) for i in range(N)]
        D.append(moving_avg(moving_min(a, w2), w2))

    kerb = [[0] * N, [0] * N]
    grav = [[0] * N, [0] * N]
    for i in range(N):
        ak = abs(kap[i])
        if S["kerbs"] and ak > 1 / KERB_R:
            kerb[0][i] = kerb[1][i] = 1
        if S["gravel"] and ak > 1 / GRAVEL_R:
            grav[1 if kap[i] > 0 else 0][i] = 1
    for si in (0, 1):
        kerb[si] = remove_short(dilate(kerb[si], round(8 / h), round(8 / h)), round(12 / h))
        grav[si] = dilate(grav[si], round(15 / h), round(40 / h))
        for i in range(N):
            is_pit = si == pit_si and in_pit[i]
            if is_pit:
                kerb[si][i] = 0
            if is_pit or D[si][i] - half - KERB_W < 8:
                grav[si][i] = 0
        remove_short(grav[si], round(20 / h))
    flags = []
    for i in range(N):
        f = 0
        f |= 1 if kerb[0][i] else 0
        f |= 2 if kerb[1][i] else 0
        f |= 4 if grav[0][i] else 0
        f |= 8 if grav[1][i] else 0
        f |= 16 if (pit_si == 0 and in_pit[i]) else 0
        f |= 32 if (pit_si == 1 and in_pit[i]) else 0
        flags.append(f)

    # ---- spawn points & timing gates ----
    def at(s):
        return round(s / h) % N

    first_turn = sum(kap[i] for i in range(min(N, round(400 / h))))
    pole = -1 if first_turn < 0 else 1
    objects = []
    for k in range(S["pitBoxes"]):
        objects.append(dict(name=f"AC_START_{k}", i=at(-(6 + plan["gridGap"] * k)),
                            offset=(pole if k % 2 == 0 else -pole) * S["roadWidth"] / 4))
    pit_sign = 1 if pit_si == 0 else -1
    k = slot = 0
    while k < S["pitBoxes"]:
        i = at(-(30 + 10 * slot))
        apron = min(APRON_W, D[pit_si][i] - half - 1)
        # two cars side by side where the apron is wide enough, otherwise one in the middle
        for across in ((0.27, 0.73) if plan["rows"] == 2 and apron >= 9 else (0.5,)):
            if k >= S["pitBoxes"]:
                break
            objects.append(dict(name=f"AC_PIT_{k}", i=i, offset=pit_sign * (half + apron * across)))
            k += 1
        slot += 1
    objects.append(dict(name="AC_HOTLAP_START_0", i=at(-min(200, 0.15 * m["L"])), offset=0.0))
    for k, f in enumerate((0, 1 / 3, 2 / 3)):
        i = at(f * m["L"])
        objects.append(dict(name=f"AC_TIME_{k}_L", i=i, offset=half + 1.5))
        objects.append(dict(name=f"AC_TIME_{k}_R", i=i, offset=-(half + 1.5)))

    m.update(S=S, nx=nx, ny=ny, kap=kap, D=D, flags=flags, objects=objects, pitSi=pit_si, half=half,
             stats=dict(length=m["L"], corners=corners, minRadius=min_r, maxGradient=max_g * 100,
                        direction=direction, pitSide="left" if pit_si == 0 else "right"))
    return m


def layout_from_doc(doc):
    """Build a full layout dict (same shape as the designer's export) from points + settings."""
    m = compute(doc)
    r3 = lambda v: round(v, 3)
    S = dict(m["S"], kerbWidth=KERB_W, apronWidth=APRON_W)
    return dict(
        format="ac-track-layout", version=1, generator="layout_core.py",
        name=doc.get("name") or "My Circuit", id=doc.get("id") or slugify(doc.get("name")), author=doc.get("author", ""),
        settings=S,
        stats={k: (r3(v) if isinstance(v, float) else v) for k, v in m["stats"].items()},
        points=doc["points"],
        sampleSpacing=r3(m["h"]),
        sampleFields=["x", "y", "z", "rollDeg", "wallLeft", "wallRight", "flags"],
        flagBits=dict(kerbLeft=1, kerbRight=2, gravelLeft=4, gravelRight=8, pitLeft=16, pitRight=32),
        samples=[[r3(m["x"][i]), r3(m["y"][i]), r3(m["z"][i]), r3(m["roll"][i]), r3(m["D"][0][i]), r3(m["D"][1][i]), m["flags"][i]]
                 for i in range(m["N"])],
        objects=[dict(o, offset=r3(o["offset"])) for o in m["objects"]],
    )


def load_layout(path):
    """Read a layout file; fill in samples from the control points when they're missing."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    if not doc.get("samples"):
        doc = layout_from_doc(doc)
    doc.setdefault("id", slugify(doc.get("name")))
    doc["id"] = slugify(doc["id"])
    return doc


if __name__ == "__main__":
    lay = load_layout(sys.argv[1])
    print(json.dumps(dict(id=lay["id"], samples=len(lay["samples"]), stats=lay["stats"]), indent=2))
