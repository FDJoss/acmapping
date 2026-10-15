"""Paste a generated track library into the designer, between its TRACK-LIBRARY markers.

usage: python -I inject_library.py <library.json> <track-designer.html>
"""
import json
import re
import sys

lib_path, html_path = sys.argv[1:3]
tracks = json.load(open(lib_path, encoding="utf-8"))
body = "[\n" + ",\n".join(json.dumps(t, separators=(",", ":"), ensure_ascii=False) for t in tracks) + "\n]"
page = open(html_path, encoding="utf-8").read()
new, n = re.subn(r"/\* TRACK-LIBRARY:BEGIN \*/.*?/\* TRACK-LIBRARY:END \*/",
                 lambda m: "/* TRACK-LIBRARY:BEGIN */" + body + "/* TRACK-LIBRARY:END */", page, flags=re.S)
if n != 1:
    sys.exit("TRACK-LIBRARY markers not found exactly once")
open(html_path, "w", encoding="utf-8").write(new)
print(f"injected {len(tracks)} tracks ({len(body) / 1024:.0f} KB) into {html_path}")
