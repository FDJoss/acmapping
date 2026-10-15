"""Render a numbered PNG contact sheet of every layout in a library file (no external libraries).

usage: python -I contact_png.py <builder_dir> <library.json> <out.png> [columns]
Cell n shows track n (printed as an index). Dark line = track, orange = banked, red dot = start/finish,
green dot = a little way into the lap (shows the direction), blue tick = pit side at the start line.
"""
import json
import math
import struct
import sys
import zlib

import numpy as np

FONT = {  # 3x5 digits
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001010010010",
    "8": "111101111101111", "9": "111101111001111",
}


def point(p):
    """Library points are [x, y, z, bank] (older libraries: [x, y, bank])."""
    if len(p) >= 4:
        return dict(x=p[0], y=p[1], z=p[2], bank=p[3])
    return dict(x=p[0], y=p[1], z=0, bank=p[2])


def write_png(path, img):
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].astype(np.uint8).tobytes() for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


def disc(img, x, y, r, col):
    h, w, _ = img.shape
    R = int(math.ceil(r))
    for yy in range(max(0, int(y) - R), min(h, int(y) + R + 1)):
        for xx in range(max(0, int(x) - R), min(w, int(x) + R + 1)):
            if (xx - x) ** 2 + (yy - y) ** 2 <= r * r:
                img[yy, xx] = col


def text(img, x, y, s, scale, col):
    for k, ch in enumerate(s):
        bits = FONT.get(ch)
        if not bits:
            continue
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] == "1":
                    img[y + r * scale:y + (r + 1) * scale, x + (k * 4 + c) * scale:x + (k * 4 + c + 1) * scale] = col


def main():
    builder, lib, out = sys.argv[1:4]
    cols = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    sys.path.insert(0, builder)
    import layout_core as lc
    tracks = json.load(open(lib, encoding="utf-8"))
    cell = 240
    rows = math.ceil(len(tracks) / cols)
    img = np.full((rows * cell, cols * cell, 3), 255, np.uint8)
    for n, e in enumerate(tracks):
        doc = dict(name=e["name"], settings=e["settings"], points=[point(p) for p in e["points"]])
        lay = lc.layout_from_doc(doc)
        S = np.array(lay["samples"])
        X, Y, roll, flags = S[:, 0], S[:, 1], S[:, 3], S[:, 6].astype(int)
        ox, oy = (n % cols) * cell, (n // cols) * cell
        img[oy:oy + cell, ox] = 220
        img[oy, ox:ox + cell] = 220
        pad = 22
        k = (cell - 2 * pad) / max(X.max() - X.min(), Y.max() - Y.min())
        cx = ox + cell / 2 - (X.max() + X.min()) / 2 * k
        cy = oy + cell / 2 + 6 + (Y.max() + Y.min()) / 2 * k
        for i in range(0, len(X), 3):
            col = (232, 89, 12) if abs(roll[i]) > 3 else (40, 40, 40)
            disc(img, cx + X[i] * k, cy - Y[i] * k, 1.6, col)
        a = int(len(X) * 0.04)
        disc(img, cx + X[a] * k, cy - Y[a] * k, 4, (47, 158, 68))
        disc(img, cx + X[0] * k, cy - Y[0] * k, 5, (220, 20, 20))
        # pit side tick
        if e["settings"]["pitSide"] in ("left", "right"):
            fx, fy = X[3] - X[0], Y[3] - Y[0]
            ln = math.hypot(fx, fy) or 1
            sg = 1 if e["settings"]["pitSide"] == "left" else -1
            nx, ny = -fy / ln * sg, fx / ln * sg
            for t in range(6, 16):
                disc(img, cx + X[0] * k + nx * t, cy - Y[0] * k - ny * t, 1.5, (25, 113, 194))
        text(img, ox + 6, oy + 6, str(n + 1), 3, (0, 0, 0))
    write_png(out, img)
    for n, e in enumerate(tracks):
        print(f"{n + 1:2d} {e['id']}: {e['name']} - {e['config']}")


if __name__ == "__main__":
    main()
