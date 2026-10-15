"""Download OpenStreetMap data (circuit relations + raceway ways) for every catalogue track.

usage: python -I osm_fetch.py <cache_dir> [--reverse] [--servers=a,b] [track_id ...]
Results are cached per venue; existing files are skipped. Public Overpass servers are busy, so this retries
politely across a few of them. Two copies can run at once (one with --reverse) to meet in the middle.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from track_catalog import TRACKS  # noqa: E402

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
UA = "acmapping-track-importer/1.0 (personal Assetto Corsa modding project)"


def radius(t):
    return int(min(4000, 0.4 * t["length"] + 400))


def cache_name(t):
    return f"{t['lat']:.4f}_{t['lon']:.4f}_{radius(t)}.json"


def query(t):
    # a bounding box is much cheaper for the server than an "around" search
    r, lat, lon = radius(t), t["lat"], t["lon"]
    dlat = r / 111320.0
    dlon = r / (111320.0 * max(0.2, __import__("math").cos(__import__("math").radians(lat))))
    bb = f"{lat - dlat:.5f},{lon - dlon:.5f},{lat + dlat:.5f},{lon + dlon:.5f}"
    # small stadium ovals are often mapped as leisure=track with sport=motor instead of highway=raceway
    return (f'[out:json][timeout:180][bbox:{bb}];(relation["type"="circuit"];way["highway"="raceway"];'
            f'way["leisure"="track"]["sport"~"motor|racing"];);(._;>;);out body;')


def fetch(q):
    data = urllib.parse.urlencode({"data": q}).encode()
    delay = 10
    for attempt in range(8):
        for ep in ENDPOINTS:
            req = urllib.request.Request(ep, data=data, headers={"User-Agent": UA, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=200) as resp:
                    body = resp.read()
                json.loads(body)                    # make sure it's complete JSON
                return body, ep
            except urllib.error.HTTPError as e:
                print(f"    {ep.split('/')[2]}: HTTP {e.code}", flush=True)
                if e.code == 429:
                    time.sleep(delay)
            except Exception as e:                  # timeouts, resets, truncated JSON
                print(f"    {ep.split('/')[2]}: {type(e).__name__}", flush=True)
        time.sleep(delay)
        delay = min(120, delay * 2)
    raise RuntimeError("all Overpass servers failed")


def main():
    global ENDPOINTS
    cache = sys.argv[1]
    flags = [a for a in sys.argv[2:] if a.startswith("--")]
    only = {a for a in sys.argv[2:] if not a.startswith("--")}
    for f in flags:
        if f.startswith("--servers="):
            pick = f.split("=", 1)[1].split(",")
            ENDPOINTS = [e for e in ENDPOINTS if any(p in e for p in pick)]
    os.makedirs(cache, exist_ok=True)
    order = list(reversed(TRACKS)) if "--reverse" in flags else TRACKS
    for t in order:
        if only and t["id"] not in only:
            continue
        path = os.path.join(cache, cache_name(t))
        if os.path.exists(path):
            print(f"{t['id']}: cached", flush=True)
            continue
        print(f"{t['id']}: fetching (radius {radius(t)} m)", flush=True)
        try:
            body, ep = fetch(query(t))
        except RuntimeError as e:
            print(f"{t['id']}: FAILED {e}", flush=True)
            continue
        with open(path, "wb") as fh:
            fh.write(body)
        n = len(json.loads(body).get("elements", []))
        print(f"{t['id']}: {n} elements from {ep.split('/')[2]}", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
