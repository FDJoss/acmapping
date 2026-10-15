"""Assetto Corsa track builder for Blender (tested with Blender 5.2).

Turns a layout file from designer/track-designer.html into:

    output/<id>/fbx/<id>.fbx  (+ texture/*.png)   open in ksEditor, save as <id>.kn5
    output/<id>/blender/<id>.blend                 for tweaking or decorating by hand
    output/<id>/track/<id>/                        the Assetto Corsa track folder (ui, data, map...)

Run it by dragging a layout file onto build_track.bat, or:

    blender --background --factory-startup --python build_track.py -- --layout my.layout.json [--out DIR]

Naming follows Kunos' conventions: physical surfaces are "<n>ROAD", "<n>KERB", "<n>GRASS",
"<n>SAND", "<n>WALL"; spawn/timing dummies are AC_START_n, AC_PIT_n, AC_HOTLAP_START_0, AC_TIME_n_L/R.
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree


def _script_dir():
    cands = []
    if "__file__" in globals():
        cands.append(os.path.dirname(os.path.abspath(__file__)))
    for t in bpy.data.texts:
        if t.filepath:
            cands.append(os.path.dirname(bpy.path.abspath(t.filepath)))
    for c in cands:
        if os.path.exists(os.path.join(c, "layout_core.py")):
            return c
    raise RuntimeError("Can't find layout_core.py next to build_track.py")


HERE = _script_dir()
sys.path.insert(0, HERE)
import layout_core  # noqa: E402

# ---------------------------------------------------------------- tuning
WALL_H = 1.2          # visible wall height (m)
WALL_T = 0.4          # wall thickness (m)
WALL_BURY = 1.5       # how far walls reach below the ground, hides the terrain seam (m)
KERB_HUMP = 0.05      # kerb crown height (m)
DRAIN = 0.015         # off-road ground falls away from the road at 1.5 %
BUFFER = 3.0          # strip of grass between kerb and gravel trap (m)
CHUNK_M = 300.0       # split long strips into objects of about this length (m)
TERRAIN_CELL = 10.0   # terrain grid spacing (m)
TERRAIN_MARGIN = 700.0
TERRAIN_TILE = 100    # cells per terrain object (keeps vertex counts well under 65k)
GRASS_TILE, GRAVEL_TILE, CONCRETE_TILE, KERB_TILE, WALL_TILE = 8.0, 4.0, 6.0, 2.0, 4.0
DECAL_LIFT = 0.012    # paint sits this far above the asphalt (m)

PHYSICAL = ("ROAD", "KERB", "GRASS", "SAND", "WALL")


def log(msg):
    print(f"[build_track] {msg}", flush=True)


# ---------------------------------------------------------------- track geometry
class Track:
    def __init__(self, lay):
        S = lay["settings"]
        a = np.asarray(lay["samples"], dtype=np.float64)
        self.lay = lay
        self.S = S
        self.N = len(a)
        self.x, self.y, self.z = a[:, 0].copy(), a[:, 1].copy(), a[:, 2].copy()
        roll = np.radians(a[:, 3])                      # + = left side up
        self.cosr, self.sinr = np.cos(roll), np.sin(roll)
        self.D = [a[:, 4].copy(), a[:, 5].copy()]
        self.flags = a[:, 6].astype(np.int64)
        self.road_w = float(S.get("roadWidth", 12))
        self.half = self.road_w / 2
        # banking tilts the road surface, so its edges come in horizontally and move up/down
        self.E = self.half * self.cosr                  # horizontal distance from centreline to either road edge
        self.H = self.half * self.sinr                  # height of the left edge above the centre (right edge: -H)
        self.kb = float(S.get("kerbWidth", layout_core.KERB_W))
        self.apron_w = float(S.get("apronWidth", layout_core.APRON_W))
        seg = np.hypot(np.roll(self.x, -1) - self.x, np.roll(self.y, -1) - self.y)
        self.L = float(seg.sum())
        self.h = self.L / self.N
        tx = np.roll(self.x, -1) - np.roll(self.x, 1)
        ty = np.roll(self.y, -1) - np.roll(self.y, 1)
        ln = np.hypot(tx, ty)
        ln[ln == 0] = 1
        self.fx, self.fy = tx / ln, ty / ln          # forward
        self.nx, self.ny = -self.fy, self.fx          # left
        self.chunk_rows = max(20, int(round(CHUNK_M / self.h)))
        self.n_chunks = math.ceil(self.N / self.chunk_rows)
        self._fix_folds()
        # lowest ground level across the corridor at each sample: the terrain sits here and walls reach below it
        reach = np.maximum(self.D[0], self.D[1]) + WALL_T
        self.z_low = self.z - np.abs(self.H) - DRAIN * (reach - self.E) - 0.5
        self.z_floor = self._floor(reach)

    def _floor(self, reach):
        """Lowest ground level near each sample, counting other parts of the lap that pass close by lower down
        (e.g. Monaco's road to Portier under the Loews hairpin). The ground between them sits at the lower level
        and the upper road's walls reach down to it, like a retaining wall."""
        floor = self.z_low.copy()
        kd = KDTree(self.N)
        for i in range(self.N):
            kd.insert((self.x[i], self.y[i], 0.0), i)
        kd.balance()
        for i in range(self.N):
            # reach past the wall by more than a terrain cell's diagonal (14 m), so no ground triangle spans the gap
            for _, j, d in kd.find_range((self.x[i], self.y[i], 0.0), reach[i] + 25.0):
                di = abs(i - j)
                along = min(di, self.N - di) * self.h
                # "another part of the lap": much further away along the track than in a straight line
                # (a hairpin's other leg counts; the next few metres of the same road don't)
                if along > 2 * d + 10 and self.z_low[j] < floor[i]:
                    floor[i] = self.z_low[j]
        return floor

    def _fix_folds(self):
        """Pull walls in wherever the outermost offset line would turn back on itself."""
        d_min = self.half + self.kb + 1.0
        cx, cy = np.roll(self.x, -1) - self.x, np.roll(self.y, -1) - self.y
        for si, sg in ((0, 1.0), (1, -1.0)):
            D = self.D[si]
            for _ in range(40):
                d = D + WALL_T
                ox, oy = self.x + self.nx * sg * d, self.y + self.ny * sg * d
                dx, dy = np.roll(ox, -1) - ox, np.roll(oy, -1) - oy
                bad = np.nonzero(dx * cx + dy * cy < 0.15 * self.h * self.h)[0]
                if not len(bad):
                    break
                for i in bad:
                    for k in range(-12, 13):
                        j = (i + k) % self.N
                        D[j] = max(d_min, D[j] * 0.92)
            self.D[si] = D

    # sample index for a (possibly wrapped) row
    def i(self, r):
        return r % self.N

    def z_off(self, i, sg, a):
        """Ground height beyond the road edge, `a` metres (horizontally) from the centreline on side sg (+1 left, -1 right)."""
        return self.z[i] + sg * self.H[i] - DRAIN * (a - self.E[i])

    def lat_pt(self, i, d):
        """Point at lateral position d (+ = left). Up to the road edge d is measured along the banked surface;
        beyond the edge it carries on horizontally across the ground."""
        sg = 1.0 if d >= 0 else -1.0
        a = abs(d)
        if a <= self.half:
            x, y = self.xy(i, d * self.cosr[i])
            return x, y, self.z[i] + d * self.sinr[i]
        ha = self.E[i] + (a - self.half)
        x, y = self.xy(i, sg * ha)
        return x, y, self.z_off(i, sg, ha)

    def xy(self, i, d):
        return self.x[i] + self.nx[i] * d, self.y[i] + self.ny[i] * d

    def pieces(self, start, length):
        """Split rows [start, start+length] into chunk-aligned pieces: yields (first_row, quads, chunk_id)."""
        r, end = start, start + length
        while r < end:
            nxt = min(end, (r // self.chunk_rows + 1) * self.chunk_rows)
            yield r, nxt - r, (r // self.chunk_rows) % self.n_chunks
            r = nxt


# ---------------------------------------------------------------- mesh accumulation
class MeshBuf:
    def __init__(self):
        self.verts, self.faces, self.uvs = [], [], []

    def grid(self, rows, cols, P, UV):
        """Quads over a rows x cols lattice. Columns must run left to right, rows forward (gives upward normals)."""
        base = len(self.verts)
        uvc = []
        for r in range(rows):
            for c in range(cols):
                self.verts.append(P(r, c))
                uvc.append(UV(r, c))
        for r in range(rows - 1):
            for c in range(cols - 1):
                a = r * cols + c
                self.faces.append((base + a, base + a + 1, base + a + cols + 1, base + a + cols))
                self.uvs.extend((uvc[a], uvc[a + 1], uvc[a + cols + 1], uvc[a + cols]))


PARTS = {}


def part(key, mat, chunk):
    return PARTS.setdefault((key, mat, chunk), MeshBuf())


# ---------------------------------------------------------------- builders
def build_road(T):
    cols = 5
    ds = [T.half * (1 - 2 * c / (cols - 1)) for c in range(cols)]
    v_len = T.L / max(1, round(T.L / T.road_w))       # tiles a whole number of times per lap
    for r0, n, ch in T.pieces(0, T.N):
        def P(r, c, r0=r0):
            return T.lat_pt(T.i(r0 + r), ds[c])

        def UV(r, c, r0=r0):
            return (c / (cols - 1), (r0 + r) * T.h / v_len)

        part("ROAD", "asphalt", ch).grid(n + 1, cols, P, UV)


def side_runs(mask):
    return layout_core.runs(mask.astype(np.int8).tolist())


def strip(T, key, mat, sg, start, length, lat, uv_mode, hump=None):
    """A strip along the track on one side. lat(i) -> lateral distances (inner to outer)."""
    for r0, n, ch in T.pieces(start, length):
        cols = len(lat(T.i(r0)))

        def col_a(r, c, r0=r0):
            vals = lat(T.i(r0 + r))
            return vals[c] if sg < 0 else vals[cols - 1 - c]      # left side: outer first

        def P(r, c, r0=r0):
            i = T.i(r0 + r)
            a = col_a(r, c)
            x, y = T.xy(i, sg * a)
            zz = T.z_off(i, sg, a)
            if hump is not None:
                zz += hump(r0 + r - start, a, i)
            return (x, y, zz)

        def UV(r, c, r0=r0):
            i = T.i(r0 + r)
            a = col_a(r, c)
            if uv_mode == "kerb":
                return ((a - T.E[i]) / T.kb, (r0 + r - start) * T.h / KERB_TILE)
            tile = {"grass": GRASS_TILE, "gravel": GRAVEL_TILE, "concrete": CONCRETE_TILE}[uv_mode]
            x, y = T.xy(i, sg * a)
            return (x / tile, y / tile)

        part(key, mat, ch).grid(n + 1, cols, P, UV)


def build_offroad(T):
    kb, E = T.kb, T.E                    # everything off-road starts at the (banked) road edge E
    for si, sg in ((0, 1.0), (1, -1.0)):
        D = T.D[si]
        pit = (T.flags & layout_core.FLAG_PIT[si]) > 0
        kerb = ((T.flags & layout_core.FLAG_KERB[si]) > 0) & ~pit
        grav = ((T.flags & layout_core.FLAG_GRAVEL[si]) > 0) & ~pit
        buf_edge = np.minimum(E + kb + BUFFER, D - 0.5)
        aw = np.clip(np.minimum(T.apron_w, D - E - 1.0), 2.0, None)

        # shoulder: kerb or grass
        for start, ln in side_runs(kerb):
            taper_rows = max(1, 2.0 / T.h)

            def hump(rr, a, i, ln=ln):
                t = min(1.0, rr / taper_rows, (ln - rr) / taper_rows)
                return KERB_HUMP * max(0.0, t) * math.sin(math.pi * (a - E[i]) / kb)
            strip(T, "KERB", "kerb", sg, start, ln, lambda i: (E[i], E[i] + kb / 2, E[i] + kb), "kerb", hump)
        for start, ln in side_runs(~kerb & ~pit):
            strip(T, "GRASS", "grass", sg, start, ln, lambda i: (E[i], E[i] + kb / 2, E[i] + kb), "grass")
        # buffer grass, then gravel trap or grass out to the wall
        for start, ln in side_runs(~pit):
            strip(T, "GRASS", "grass", sg, start, ln, lambda i: (E[i] + kb, buf_edge[i]), "grass")
        for start, ln in side_runs(grav):
            strip(T, "SAND", "gravel", sg, start, ln, lambda i: (buf_edge[i], (buf_edge[i] + D[i]) / 2, D[i]), "gravel")
        for start, ln in side_runs(~grav & ~pit):
            strip(T, "GRASS", "grass", sg, start, ln, lambda i: (buf_edge[i], D[i]), "grass")
        # pit apron (driveable concrete, physically ROAD) and grass behind it
        for start, ln in side_runs(pit):
            strip(T, "ROAD", "concrete", sg, start, ln, lambda i: (E[i], E[i] + aw[i] / 2, E[i] + aw[i]), "concrete")
            strip(T, "GRASS", "grass", sg, start, ln, lambda i: (E[i] + aw[i], D[i]), "grass")


def build_walls(T):
    prof = [(0.0, "bottom"), (0.0, "top"), (WALL_T, "top"), (WALL_T, "bottom")]   # (extra a, level) inner->outer
    span = WALL_BURY + WALL_H
    for si, sg in ((0, 1.0), (1, -1.0)):
        D = T.D[si]
        base = T.z + sg * T.H - DRAIN * (D - T.E)          # ground level at the foot of the wall (= z_off)
        top = base + WALL_H
        # reach below the lowest ground of the corridor: on the high side of banking this becomes a retaining wall
        bottom = np.minimum(base - WALL_BURY, T.z_floor - 1.0)
        order = list(range(4)) if sg < 0 else list(reversed(range(4)))   # columns left to right
        outer_face = 2 if sg < 0 else 0
        for r0, n, ch in T.pieces(0, T.N):
            for face in range(3):          # inner face, top, outer face: separate grids keep the edges crisp
                outer = face == outer_face

                def P(r, c, r0=r0, face=face):
                    i = T.i(r0 + r)
                    da, level = prof[order[face + c]]
                    x, y = T.xy(i, sg * (D[i] + da))
                    return (x, y, top[i] if level == "top" else bottom[i])

                def UV(r, c, r0=r0, face=face, outer=outer):
                    i = T.i(r0 + r)
                    da, level = prof[order[face + c]]
                    zz = top[i] if level == "top" else bottom[i]
                    if outer:                                  # plain concrete panels, mapped by height
                        return ((r0 + r) * T.h / CONCRETE_TILE, zz / CONCRETE_TILE)
                    v = 1.0 + da / span if face == 1 else 1.0 - (top[i] - zz) / span
                    return ((r0 + r) * T.h / WALL_TILE, v)

                part("WALL", "concrete" if outer else "barrier", ch).grid(n + 1, 2, P, UV)


def build_terrain(T):
    """Visual ground beyond the walls: sits just under the track corridor and blends out to the surroundings."""
    ox = np.concatenate([T.x + T.nx * (T.D[0] + WALL_T), T.x - T.nx * (T.D[1] + WALL_T)])
    oy = np.concatenate([T.y + T.ny * (T.D[0] + WALL_T), T.y - T.ny * (T.D[1] + WALL_T)])
    x0 = math.floor((ox.min() - TERRAIN_MARGIN) / TERRAIN_CELL) * TERRAIN_CELL
    y0 = math.floor((oy.min() - TERRAIN_MARGIN) / TERRAIN_CELL) * TERRAIN_CELL
    nxg = int(math.ceil((ox.max() + TERRAIN_MARGIN - x0) / TERRAIN_CELL)) + 1
    nyg = int(math.ceil((oy.max() + TERRAIN_MARGIN - y0) / TERRAIN_CELL)) + 1
    gx = x0 + np.arange(nxg) * TERRAIN_CELL
    gy = y0 + np.arange(nyg) * TERRAIN_CELL
    PX, PY = np.meshgrid(gx, gy)                      # (nyg, nxg)
    px, py = PX.ravel(), PY.ravel()

    kd = KDTree(T.N)
    for i in range(T.N):
        kd.insert((T.x[i], T.y[i], 0.0), i)
    kd.balance()
    near = np.empty(len(px), np.int64)
    dist = np.empty(len(px))
    for k in range(len(px)):
        _, j, d = kd.find((px[k], py[k], 0.0))
        near[k], dist[k] = j, d
    side = ((px - T.x[near]) * T.nx[near] + (py - T.y[near]) * T.ny[near]) < 0   # True = right
    sgn = np.where(side, -1.0, 1.0)
    d_wall = np.where(side, T.D[1][near], T.D[0][near])
    wall = d_wall + WALL_T
    zn, En, Hn, tn = T.z[near], T.E[near], T.H[near], T.sinr[near] / T.cosr[near]
    d_left, d_right = T.D[0][near], T.D[1][near]

    def surface(s):
        """Track surface height at signed lateral position s (+ = left, horizontal metres) of the nearest sample."""
        a, sg = np.abs(s), np.where(s >= 0, 1.0, -1.0)
        return np.where(a <= En, zn + s * tn, zn + sg * Hn - DRAIN * (a - En))

    def below(s):
        """0.6 m under the lowest surface within 15 m either side of s. A 10 m terrain triangle never spans more
        than that, so whole triangles stay under the track. The cross-section only has one peak, so its lowest
        point inside any window is at one of the window's ends."""
        lo, hi = np.maximum(s - 15.0, -d_right), np.minimum(s + 15.0, d_left)
        return np.minimum(surface(lo), surface(hi)) - 0.6

    # where another part of the lap passes close by lower down, the ground sits at that lower level
    z_in = np.minimum(below(sgn * np.minimum(dist, d_wall)), T.z_floor[near])
    # outside the wall the ground carries on from the level it had at the wall, so the two always meet
    z_edge = np.minimum(below(sgn * d_wall), T.z_floor[near])

    # smooth "far" height: inverse-distance average of the track's elevation
    step = max(1, int(round(10 / T.h)))
    sx, sy, sz = T.x[::step], T.y[::step], T.z[::step]
    z_far = np.empty(len(px))
    for a in range(0, len(px), 4000):
        dx = px[a:a + 4000, None] - sx[None, :]
        dy = py[a:a + 4000, None] - sy[None, :]
        w = 1.0 / (dx * dx + dy * dy + 400.0)
        z_far[a:a + 4000] = (w * sz).sum(1) / w.sum(1)
    t = np.clip((dist - wall) / 60.0, 0.0, 1.0)
    t = t * t * (3 - 2 * t)
    zt = np.where(dist <= wall, z_in, (1 - t) * z_edge + t * z_far).reshape(nyg, nxg)

    tiles = 0
    for ty0 in range(0, nyg - 1, TERRAIN_TILE):
        for tx0 in range(0, nxg - 1, TERRAIN_TILE):
            ty1, tx1 = min(nyg - 1, ty0 + TERRAIN_TILE), min(nxg - 1, tx0 + TERRAIN_TILE)
            mb = part("TERRAIN", "terrain", tiles)
            mb.grid(ty1 - ty0 + 1, tx1 - tx0 + 1,
                    lambda r, c, ty0=ty0, tx0=tx0: (gx[tx0 + c], gy[ty0 + r], zt[ty0 + r, tx0 + c]),
                    lambda r, c, ty0=ty0, tx0=tx0: (gx[tx0 + c] / GRASS_TILE, gy[ty0 + r] / GRASS_TILE))
            tiles += 1
    log(f"terrain {nxg}x{nyg} vertices in {tiles} tiles")


def build_decals(T, objects):
    """Start/finish line, grid boxes and pit box lines (visual only)."""
    def quad(mb, i, along0, along1, left, right):
        """A flat quad around sample i: `along` is metres forward, `left`/`right` are lateral offsets (+ = left)."""
        slope = (T.z[(i + 1) % T.N] - T.z[(i - 1) % T.N]) / (2 * T.h)

        def P(r, c):
            al = along0 if r == 0 else along1
            x, y, zz = T.lat_pt(i, left if c == 0 else right)
            return (x + T.fx[i] * al, y + T.fy[i] * al, zz + slope * al + DECAL_LIFT)

        mb.grid(2, 2, P, lambda r, c: (float(c), float(r)))

    quad(part("STARTLINE", "startline", 0), 0, -0.6, 0.6, T.half, -T.half)
    lines = part("LINES", "lines", 0)
    boxes = set()
    for o in objects:
        i, off = o["i"], o["offset"]
        if o["name"].startswith("AC_START_"):
            quad(lines, i, 2.4, 2.65, off + 1.3, off - 1.3)
        elif o["name"].startswith("AC_PIT_") and i not in boxes:     # two-row pits share one set of lines
            boxes.add(i)
            si = 0 if off > 0 else 1
            aw = min(T.apron_w, T.D[si][i] - T.E[i] - 1.0)          # same apron width the builder paves
            inner, outer = T.half + 0.3, T.half + aw - 0.3          # across the apron (surface coordinates)
            left, right = (outer, inner) if off > 0 else (-inner, -outer)
            for al in (-5.0, 5.0):
                quad(lines, i, al - 0.1, al + 0.1, left, right)


# ---------------------------------------------------------------- textures (procedural)
def _noise(size, cells, rng):
    g = rng.random((cells, cells))
    t = np.arange(size) * cells / size
    i0 = np.floor(t).astype(np.int64)
    f = t - i0
    f = f * f * (3 - 2 * f)
    i1 = (i0 + 1) % cells
    i0 %= cells
    rows = g[i0] * (1 - f)[:, None] + g[i1] * f[:, None]
    return rows[:, i0] * (1 - f)[None, :] + rows[:, i1] * f[None, :]


def fbm(size, rng, base=4, octaves=6, persist=0.55):
    tot, amp, norm = np.zeros((size, size)), 1.0, 0.0
    for o in range(octaves):
        c = base * 2 ** o
        if c > size:
            break
        tot += amp * _noise(size, c, rng)
        norm += amp
        amp *= persist
    return tot / norm


def rgba(base, shade):
    """base: rgb triple, shade: (h, w) multiplier."""
    img = np.empty(shade.shape + (4,), np.float32)
    for k in range(3):
        img[..., k] = np.clip(base[k] * shade, 0, 1)
    img[..., 3] = 1.0
    return img


def save_image(arr, path, name):
    """arr: (h, w, 4) floats, row 0 at the BOTTOM (Blender's convention)."""
    h, w = arr.shape[:2]
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels.foreach_set(np.ascontiguousarray(arr, dtype=np.float32).ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    img.filepath = path
    return img


def make_textures(tex_dir, T):
    rng = np.random.default_rng(7)
    os.makedirs(tex_dir, exist_ok=True)
    out = {}
    S = 1024

    # asphalt: u runs across the road, white edge lines on both sides
    shade = 0.82 + 0.25 * (fbm(S, rng, 4) - 0.5) + 0.16 * (rng.random((S, S)) - 0.5)
    shade += (rng.random((S, S)) > 0.985) * 0.35
    img = rgba((0.25, 0.25, 0.26), shade)
    lw = max(4, int(round(0.2 / T.road_w * S)))
    wear = 0.86 + 0.1 * fbm(S, rng, 16)
    for k in range(3):
        img[:, :lw, k] = wear[:, :lw]
        img[:, -lw:, k] = wear[:, -lw:]
    out["asphalt"] = img

    # kerb: red/white stripes along v (one pair per KERB_TILE metres)
    v = (np.arange(S) + 0.5) / S
    red = (v < 0.5)[:, None] * np.ones((1, S), bool)
    grime = 0.9 + 0.12 * fbm(S, rng, 8) + 0.05 * (rng.random((S, S)) - 0.5)
    img = np.empty((S, S, 4), np.float32)
    for k, (rc, wc) in enumerate(((0.74, 0.92), (0.09, 0.92), (0.08, 0.9))):
        img[..., k] = np.clip(np.where(red, rc, wc) * grime, 0, 1)
    img[..., 3] = 1
    out["kerb"] = img

    # grass
    big, mid = fbm(S, rng, 2), fbm(S, rng, 8)
    shade = 0.8 + 0.35 * (big - 0.5) + 0.25 * (mid - 0.5) + 0.22 * (rng.random((S, S)) - 0.5)
    img = rgba((0.23, 0.40, 0.13), shade)
    img[..., 0] *= 1 + 0.25 * (big - 0.5)
    out["grass"] = img

    # terrain: same idea, darker and with larger patches
    big, mid = fbm(S, rng, 1), fbm(S, rng, 6)
    shade = 0.78 + 0.45 * (big - 0.5) + 0.2 * (mid - 0.5) + 0.18 * (rng.random((S, S)) - 0.5)
    img = rgba((0.21, 0.35, 0.12), shade)
    img[..., 0] *= 1 + 0.35 * (big - 0.5)
    out["terrain"] = img

    # gravel
    pebbles = fbm(S, rng, 128, octaves=3)
    shade = 0.8 + 0.5 * (pebbles - 0.5) + 0.3 * (rng.random((S, S)) - 0.5)
    out["gravel"] = rgba((0.66, 0.58, 0.44), shade)

    # concrete (pit apron): slab joints at the tile edges
    shade = 0.9 + 0.12 * (fbm(S, rng, 4) - 0.5) + 0.08 * (rng.random((S, S)) - 0.5)
    shade[:3, :] *= 0.6
    shade[:, :3] *= 0.6
    out["concrete"] = rgba((0.60, 0.60, 0.58), shade)

    # barrier: v=0 bottom of the buried part, v=1 top of the wall
    v = (np.arange(S) + 0.5) / S
    vis = WALL_BURY / (WALL_BURY + WALL_H)
    shade = 0.92 + 0.1 * (fbm(S, rng, 8) - 0.5) + 0.06 * (rng.random((S, S)) - 0.5)
    grime = np.clip((v - vis) / 0.25, 0, 1)[:, None] * 0.45 + 0.55
    shade = shade * grime
    shade[:, :4] *= 0.7
    img = rgba((0.72, 0.72, 0.70), shade)
    band = (v > 0.9)[:, None] & np.ones((1, S), bool)
    img[band, 0], img[band, 1], img[band, 2] = 0.75, 0.12, 0.10
    out["barrier"] = img

    out["lines"] = rgba((0.93, 0.93, 0.91), np.ones((32, 32)))

    # start/finish: two rows of chequers across the road
    cw, chh = 512, 64
    u = (np.arange(cw) * 16 // cw)[None, :]
    vv = (np.arange(chh) * 2 // chh)[:, None]
    chk = ((u + vv) % 2).astype(np.float32)
    img = np.empty((chh, cw, 4), np.float32)
    img[..., 0] = img[..., 1] = img[..., 2] = 0.06 + chk * 0.86
    img[..., 3] = 1
    out["startline"] = img

    images = {}
    for name, arr in out.items():
        images[name] = save_image(arr, os.path.join(tex_dir, name + ".png"), "tx_" + name)
    return images


def make_material(name, img, rough=0.85):
    m = bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        outn = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None) or nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs["BSDF"], outn.inputs["Surface"])
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.location = (-350, 250)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    return m


# ---------------------------------------------------------------- scene objects
def reset_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.cameras, bpy.data.lights):
        for b in list(coll):
            coll.remove(b)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def collection(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


def create_objects(mats):
    counters, made = {}, []
    groups = {"ROAD": "TRACK", "KERB": "TRACK", "GRASS": "TRACK", "SAND": "TRACK", "WALL": "WALLS",
              "TERRAIN": "TERRAIN", "STARTLINE": "DECALS", "LINES": "DECALS"}
    for (key, mat, ch) in sorted(PARTS, key=lambda k: (k[0], k[1], k[2])):
        mb = PARTS[(key, mat, ch)]
        if not mb.faces:
            continue
        counters[key] = counters.get(key, 0) + 1
        name = f"{counters[key]}{key}" if key in PHYSICAL else f"{key}_{counters[key]:02d}"
        if len(mb.verts) > 65000:
            raise RuntimeError(f"{name} has {len(mb.verts)} vertices; kn5 meshes are limited to 65535")
        me = bpy.data.meshes.new(name)
        me.from_pydata(mb.verts, [], mb.faces)
        me.validate(clean_customdata=False)
        if len(me.polygons) != len(mb.faces):
            raise RuntimeError(f"{name}: mesh validation dropped faces")
        uvl = me.uv_layers.new(name="UVMap")
        uvl.data.foreach_set("uv", np.asarray(mb.uvs, dtype=np.float32).ravel())
        me.polygons.foreach_set("use_smooth", np.ones(len(mb.faces), dtype=bool))
        me.materials.append(mats[mat])
        me.update()
        ob = bpy.data.objects.new(name, me)
        collection(groups.get(key, "TRACK")).objects.link(ob)
        made.append((name, len(mb.verts), len(mb.faces)))
    return made


def place_dummies(T, objects, flip=False):
    """Empties use Kunos' orientation: local Z points along the track, local Y points up.
    With the FBX export settings below (Y up, -Z forward) that matches what 3ds Max exports."""
    coll = collection("AC_OBJECTS")
    for o in objects:
        i, off, name = o["i"], o["offset"], o["name"]
        a, b = (i - 2) % T.N, (i + 2) % T.N
        f = Vector((T.x[b] - T.x[a], T.y[b] - T.y[a], T.z[b] - T.z[a])).normalized()
        left = Vector((T.nx[i] * T.cosr[i], T.ny[i] * T.cosr[i], T.sinr[i]))     # across the banked surface
        up = f.cross(left).normalized()
        if flip:
            f = -f
        up = (up - up.dot(f) * f).normalized()
        xl = up.cross(f)
        x, y, zz = T.lat_pt(i, off)
        zz += 0.5 if name.startswith("AC_TIME") else 0.05
        m = Matrix(((xl.x, up.x, f.x, x), (xl.y, up.y, f.y, y), (xl.z, up.z, f.z, zz), (0, 0, 0, 1)))
        ob = bpy.data.objects.new(name, None)
        ob.empty_display_type = "ARROWS"
        ob.empty_display_size = 2.0
        ob.matrix_world = m
        coll.objects.link(ob)


def export_fbx(path):
    bpy.ops.export_scene.fbx(
        filepath=path, use_selection=False, object_types={"EMPTY", "MESH"},
        global_scale=1.0, apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z", axis_up="Y", bake_space_transform=False,
        use_mesh_modifiers=True, mesh_smooth_type="FACE", use_tspace=False,
        use_custom_props=False, add_leaf_bones=False, bake_anim=False,
        path_mode="RELATIVE", embed_textures=False, batch_mode="OFF")


# ---------------------------------------------------------------- track folder (ui, data, map)
SURFACES_INI = """[SURFACE_0]
KEY=ROAD
FRICTION=1
DAMPING=0
WAV=
WAV_PITCH=0
FF_EFFECT=NULL
DIRT_ADDITIVE=0
BLACK_FLAG_TIME=0
IS_VALID_TRACK=1
SIN_HEIGHT=0
SIN_LENGTH=0
IS_PITLANE=0
VIBRATION_GAIN=0
VIBRATION_LENGTH=0

[SURFACE_1]
KEY=GRASS
FRICTION=0.6
DAMPING=0
WAV=grass.wav
WAV_PITCH=0
FF_EFFECT=NULL
DIRT_ADDITIVE=1
IS_VALID_TRACK=0
BLACK_FLAG_TIME=0
SIN_HEIGHT=0.03
SIN_LENGTH=0.5
IS_PITLANE=0
VIBRATION_GAIN=0.2
VIBRATION_LENGTH=0.6

[SURFACE_2]
KEY=KERB
FRICTION=0.92
DAMPING=0
WAV=kerb.wav
WAV_PITCH=1.3
FF_EFFECT=1
DIRT_ADDITIVE=0
BLACK_FLAG_TIME=0
IS_VALID_TRACK=1
SIN_HEIGHT=0
SIN_LENGTH=0
IS_PITLANE=0
VIBRATION_GAIN=1.0
VIBRATION_LENGTH=1.5

[SURFACE_3]
KEY=SAND
FRICTION=0.8
DAMPING=0.1
WAV=sand.wav
WAV_PITCH=0
FF_EFFECT=0
DIRT_ADDITIVE=1
IS_VALID_TRACK=0
BLACK_FLAG_TIME=0
SIN_HEIGHT=0.04
SIN_LENGTH=0.5
IS_PITLANE=0
VIBRATION_GAIN=0.2
VIBRATION_LENGTH=0.3
"""


def ac(x, y, z):
    """Blender (x, y, z-up) -> Assetto Corsa (x, y-up, z) under the FBX axis settings used here."""
    return (x, z, -y)


def raster(T, W, H, to_px, layers, ss=3, bg=(0, 0, 0, 0)):
    """Draw the track by stamping discs along the centreline. Returns (H, W, 4), row 0 at the TOP."""
    Wc, Hc = W * ss, H * ss
    cv = np.zeros((Hc, Wc, 4), np.float32)
    cv[:] = bg
    for radius_fn, color, mask in layers:
        for i in range(T.N):
            if mask is not None and not mask[i]:
                continue
            cx, cy, r = radius_fn(i)
            px, py = to_px(cx, cy)
            px, py, rr = px * ss, py * ss, r * ss
            R = int(math.ceil(rr))
            x0, x1 = max(0, int(px) - R), min(Wc, int(px) + R + 2)
            y0, y1 = max(0, int(py) - R), min(Hc, int(py) + R + 2)
            if x0 >= x1 or y0 >= y1:
                continue
            yy, xx = np.mgrid[y0:y1, x0:x1]
            m = (xx + 0.5 - px) ** 2 + (yy + 0.5 - py) ** 2 <= rr * rr
            cv[y0:y1, x0:x1][m] = color
    # downsample with premultiplied alpha so transparent pixels don't darken the edges
    cv[..., :3] *= cv[..., 3:4]
    out = cv.reshape(H, ss, W, ss, 4).mean(axis=(1, 3))
    a = out[..., 3:4]
    out[..., :3] = np.where(a > 1e-6, out[..., :3] / np.maximum(a, 1e-6), 0)
    return out


def save_top_down_png(arr_top, path, name):
    save_image(arr_top[::-1], path, name)


def write_track_folder(T, lay, track_dir):
    S = T.S
    os.makedirs(os.path.join(track_dir, "ui"), exist_ok=True)
    os.makedirs(os.path.join(track_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(track_dir, "ai"), exist_ok=True)
    os.makedirs(os.path.join(track_dir, "extension"), exist_ok=True)
    stats = lay.get("stats", {})
    direction = stats.get("direction", "clockwise")
    pit_boxes = int(S.get("pitBoxes", 12))

    ui = {
        "name": lay.get("name", "My Circuit"),
        "description": f"Original {T.L / 1000:.2f} km circuit built with the track layout designer.",
        "tags": ["circuit", "original"],
        "geotags": ["lat", "lon"],
        "country": "",
        "city": "",
        "length": str(int(round(T.L))),
        "width": f"{T.road_w:g}",
        "pitboxes": str(pit_boxes),
        "run": direction,
        "author": lay.get("author") or "",
        "version": "1.0",
        "year": time.localtime().tm_year,
    }
    with open(os.path.join(track_dir, "ui", "ui_track.json"), "w", encoding="utf-8") as fh:
        json.dump(ui, fh, indent="\t")

    with open(os.path.join(track_dir, "data", "surfaces.ini"), "w", encoding="utf-8") as fh:
        fh.write(SURFACES_INI)
    with open(os.path.join(track_dir, "data", "lighting.ini"), "w", encoding="utf-8") as fh:
        fh.write("[LIGHTING]\nSUN_PITCH_ANGLE=45\nSUN_HEADING_ANGLE=220\n")
    pit_si = 0 if stats.get("pitSide", "left") == "left" else 1
    with open(os.path.join(track_dir, "data", "crew.ini"), "w", encoding="utf-8") as fh:
        fh.write(f"[HEADER]\nSIDE={1 if pit_si == 0 else -1}\t\t; 1 = left , -1 = right\n")

    # ---- map.png / map.ini (1 px per metre, like Kunos' maps) ----
    margin = 20
    ex = np.concatenate([T.x + T.nx * T.half, T.x - T.nx * T.half])
    ey = np.concatenate([T.y + T.ny * T.half, T.y - T.ny * T.half])
    xmin, xmax = ex.min(), ex.max()
    zmin_ac, zmax_ac = -ey.max(), -ey.min()
    scale = max(1.0, max(xmax - xmin, zmax_ac - zmin_ac) / (1600 - 2 * margin))
    W = int(math.ceil((xmax - xmin) / scale + 2 * margin))
    H = int(math.ceil((zmax_ac - zmin_ac) / scale + 2 * margin))
    x_off, z_off = -xmin + margin * scale, -zmin_ac + margin * scale
    to_map = lambda x, y: ((x + x_off) / scale, (-y + z_off) / scale)
    cen = lambda r: (lambda i: (T.x[i], T.y[i], r / scale))
    arr = raster(T, W, H, to_map, [(cen(T.half + 2.5), (0.05, 0.05, 0.05, 0.75), None),
                                  (cen(T.half), (1, 1, 1, 0.95), None)], ss=2)
    save_top_down_png(arr, os.path.join(track_dir, "map.png"), "ui_map")
    with open(os.path.join(track_dir, "data", "map.ini"), "w", encoding="utf-8") as fh:
        fh.write(f"[PARAMETERS]\nWIDTH={W}\nHEIGHT={H}\nMARGIN={margin}\nSCALE_FACTOR={scale:g}\n"
                 f"MAX_SIZE=1600\nX_OFFSET={x_off:.3f}\nZ_OFFSET={z_off:.3f}\nDRAWING_SIZE=10\n")

    # ---- outline.png (white line, rotated to landscape if that fills the box better) ----
    ow, oh, pad = 365, 192, 10
    rot = (ey.max() - ey.min()) > (ex.max() - ex.min())
    rx = (lambda x, y: y) if rot else (lambda x, y: x)
    ry = (lambda x, y: -x) if rot else (lambda x, y: y)
    qx, qy = rx(T.x, T.y), ry(T.x, T.y)
    k = min((ow - 2 * pad) / (qx.max() - qx.min() + 1e-6), (oh - 2 * pad) / (qy.max() - qy.min() + 1e-6))
    cxo = (ow - (qx.max() - qx.min()) * k) / 2
    cyo = (oh - (qy.max() - qy.min()) * k) / 2
    to_out = lambda x, y: ((rx(x, y) - qx.min()) * k + cxo, (qy.max() - ry(x, y)) * k + cyo)
    arr = raster(T, ow, oh, to_out, [(lambda i: (T.x[i], T.y[i], 1.6), (1, 1, 1, 1), None)], ss=4)
    save_top_down_png(arr, os.path.join(track_dir, "ui", "outline.png"), "ui_outline")

    # ---- preview.png (stylised top-down view; replace with an in-game screenshot later) ----
    pw, ph, pad = 355, 200, 12
    wx = np.concatenate([T.x + T.nx * T.D[0], T.x - T.nx * T.D[1]])
    wy = np.concatenate([T.y + T.ny * T.D[0], T.y - T.ny * T.D[1]])
    k = min((pw - 2 * pad) / (wx.max() - wx.min()), (ph - 2 * pad) / (wy.max() - wy.min()))
    cxo, cyo = (pw - (wx.max() - wx.min()) * k) / 2, (ph - (wy.max() - wy.min()) * k) / 2
    to_prev = lambda x, y: ((x - wx.min()) * k + cxo, (wy.max() - y) * k + cyo)
    mid = lambda i: (T.x[i] + T.nx[i] * (T.D[0][i] - T.D[1][i]) / 2, T.y[i] + T.ny[i] * (T.D[0][i] - T.D[1][i]) / 2,
                     (T.D[0][i] + T.D[1][i]) / 2 * k)
    kerb_any = (T.flags & 3) > 0
    arr = raster(T, pw, ph, to_prev, [
        (mid, (0.64, 0.77, 0.47, 1), None),
        (lambda i: (T.x[i], T.y[i], (T.half + T.kb) * k), (0.83, 0.2, 0.2, 1), kerb_any),
        (lambda i: (T.x[i], T.y[i], max(T.half * k, 0.9)), (0.2, 0.21, 0.23, 1), None),
    ], ss=4, bg=(0.47, 0.64, 0.33, 1))
    save_top_down_png(arr, os.path.join(track_dir, "ui", "preview.png"), "ui_preview")

    # ---- TV cameras (positions are fractions of the lap from the start line) ----
    n_cam = max(6, int(round(T.L / 400)))
    out_si = 0 if direction == "clockwise" else 1        # outside of the circuit
    lines = [f"[HEADER]\nVERSION=3\nCAMERA_COUNT={n_cam}\nSET_NAME=TV 1\n"]
    for c in range(n_cam):
        f0, f1 = c / n_cam, (c + 1) / n_cam
        i = int(((f0 + f1) / 2) * T.N) % T.N
        sg = 1.0 if out_si == 0 else -1.0
        dpos = T.D[out_si][i] + WALL_T + 6
        cx, cy = T.xy(i, sg * dpos)
        cz = T.z_off(i, sg, T.D[out_si][i]) + 6
        tgt = Vector((T.x[i], T.y[i], T.z[i] + 1))
        cam = Vector((cx, cy, cz))
        fwd = (tgt - cam).normalized()
        right = fwd.cross(Vector((0, 0, 1))).normalized()
        up = right.cross(fwd).normalized()
        P, F, U = ac(*cam), ac(*fwd), ac(*up)
        lines.append(
            f"[CAMERA_{c}]\nNAME=cam_{c + 1}\nPOSITION={P[0]:.3f} ,{P[1]:.3f} ,{P[2]:.3f}\n"
            f"FORWARD={F[0]:.5f} ,{F[1]:.5f} ,{F[2]:.5f}\nUP={U[0]:.5f} ,{U[1]:.5f} ,{U[2]:.5f}\n"
            f"MIN_FOV=10\nMAX_FOV=45\nIN_POINT={f0:.4f}\nOUT_POINT={f1:.4f}\n"
            "SHADOW_SPLIT0=50\nSHADOW_SPLIT1=150\nSHADOW_SPLIT2=500\nNEAR_PLANE=0.5\nFAR_PLANE=10000\n"
            "MIN_EXPOSURE=0\nMAX_EXPOSURE=10000\nDOF_FACTOR=1\nDOF_RANGE=250\nDOF_FOCUS=20\nDOF_MANUAL=0\n"
            "SPLINE=\nSPLINE_ROTATION=0\nFOV_GAMMA=0.5\nSPLINE_ANIMATION_LENGTH=0\nIS_FIXED=0\n")
    with open(os.path.join(track_dir, "data", "cameras.ini"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    # ---- Custom Shaders Patch extras (ignored without CSP) ----
    with open(os.path.join(track_dir, "extension", "ext_config.ini"), "w", encoding="utf-8") as fh:
        fh.write(f"[ABOUT]\nAUTHOR = {lay.get('author') or ''}\nVERSION = 1.0\n\n"
                 "[GRASS_FX]\nGRASS_MATERIALS = grass, terrain\n"
                 "OCCLUDING_MATERIALS = asphalt, kerb, gravel, concrete, barrier, lines, startline\n")
    with open(os.path.join(track_dir, "ai", "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("Record an AI line in-game and save it here as fast_lane.ai (see GUIDE.md, step 6).\n")


# ---------------------------------------------------------------- main
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="build_track.py")
    p.add_argument("--layout", required=True, help="layout file saved by the designer")
    p.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "output"), help="output folder")
    p.add_argument("--flip-spawns", action="store_true", help="turn spawn points around if cars start backwards")
    p.add_argument("--no-terrain", action="store_true", help="skip the surrounding terrain")
    return p.parse_args(argv)


def main():
    t0 = time.time()
    args = parse_args()
    lay = layout_core.load_layout(args.layout)
    tid = lay["id"]
    root = os.path.join(os.path.abspath(args.out), tid)
    fbx_dir, blend_dir, track_dir = os.path.join(root, "fbx"), os.path.join(root, "blender"), os.path.join(root, "track", tid)
    tex_dir = os.path.join(fbx_dir, "texture")
    for d in (fbx_dir, blend_dir, track_dir, tex_dir):
        os.makedirs(d, exist_ok=True)
    log(f"building '{lay.get('name')}' ({tid}) from {args.layout}")

    reset_scene()
    PARTS.clear()
    T = Track(lay)
    log(f"{T.L:.0f} m lap, {T.N} samples, road {T.road_w:g} m")

    images = make_textures(tex_dir, T)
    mats = {name: make_material(name, img, rough=0.6 if name in ("asphalt", "kerb") else 0.9)
            for name, img in images.items()}
    log(f"textures written to {tex_dir}")

    build_road(T)
    build_offroad(T)
    build_walls(T)
    if not args.no_terrain:
        build_terrain(T)
    build_decals(T, lay["objects"])
    made = create_objects(mats)
    place_dummies(T, lay["objects"], flip=args.flip_spawns)
    log(f"{len(made)} mesh objects, {sum(m[1] for m in made)} vertices, {len(lay['objects'])} AC_ dummies")

    fbx_path = os.path.join(fbx_dir, tid + ".fbx")
    export_fbx(fbx_path)
    log(f"FBX: {fbx_path}")
    blend_path = os.path.join(blend_dir, tid + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
    log(f"blend: {blend_path}")
    write_track_folder(T, lay, track_dir)
    log(f"track folder: {track_dir}")
    log(f"done in {time.time() - t0:.1f}s")
    print("\nNEXT: open the FBX in ksEditor and save it as", os.path.join(track_dir, tid + ".kn5"), flush=True)


if __name__ == "__main__":
    main()
