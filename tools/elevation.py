"""Terrain elevation lookups from OpenTopoData (https://www.opentopodata.org), cached on disk.

Datasets are tried in order per point: ned10m (USA, 10 m, bare earth), eudem25m (Europe, 25 m), srtm30m (rest of
the world, 30 m). Points are snapped to a ~10 m grid (4 decimal places) so repeated runs reuse the cache.
The public API allows 100 points per request, 1 request per second and 1000 requests per day.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.opentopodata.org/v1/ned10m,eudem25m,srtm30m"
UA = "acmapping-track-importer/1.0 (personal Assetto Corsa modding project)"


def _key(lat, lon):
    return f"{lat:.4f},{lon:.4f}"


def lookup(latlons, cache_path, log=print):
    """Elevations (m, or None where no dataset has data) for a list of (lat, lon)."""
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)
    keys = [_key(la, lo) for la, lo in latlons]
    missing = sorted({k for k in keys if k not in cache})
    for b in range(0, len(missing), 100):
        batch = missing[b:b + 100]
        url = API + "?" + urllib.parse.urlencode({"locations": "|".join(batch)})
        for attempt in range(8):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read())
                if data.get("status") != "OK":
                    raise RuntimeError(data.get("error", "bad status"))
                for k, res in zip(batch, data["results"]):
                    cache[k] = res.get("elevation")
                break
            except (urllib.error.URLError, RuntimeError, TimeoutError, json.JSONDecodeError) as e:
                wait = 2 * (attempt + 1)
                log(f"    elevation request failed ({e}); retrying in {wait}s")
                time.sleep(wait)
        else:
            raise RuntimeError("elevation service unavailable")
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
        time.sleep(1.1)                       # stay under 1 request per second
    return [cache.get(k) for k in keys]
