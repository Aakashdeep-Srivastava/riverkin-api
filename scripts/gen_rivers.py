"""Generate data/rivers.geojson — real OSM river courses behind the monitored
sites, as a GeoJSON FeatureCollection of LineStrings.

Overpass is flaky and rate-limited (~2 slots/IP, ~10k/day), so we fetch once and
bundle the result (the same philosophy as data/site-images). The API serves the
file verbatim at GET /api/v1/maps/rivers; nothing calls Overpass at request time.

Method: group bundled sites by waterbody, compute a padded bbox from the member
coordinates, and query Overpass for named river/canal/stream ways in that box.
OSM names differ from OAH's short names (e.g. "Rio Mondego", "La Garonne", Leie↔Lys),
so NAME_HINTS maps each waterbody to a case-insensitive name regex.

Run manually when refreshing (needs network to Overpass):

    python scripts/gen_rivers.py

Attribution (ODbL, required): © OpenStreetMap contributors.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "rivers.geojson"

# Descriptive UA is REQUIRED by Overpass (a bare client gets HTTP 406).
UA = "RiverKin/1.0 (+https://riverkin.online; OneAquaHealth citizen science)"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# waterbody (as bundled) -> OSM name regex. Omitted waterbodies fall back to the
# distinctive token of the name (strip parenthetical + trailing " River").
NAME_HINTS = {
    "Mondego": "Mondego",
    "Garonne": "Garonne",
    "Leie (Lys)": "Leie|Lys",
    "Calore": "Calore",
    "Akerselva": "Akerselva",
}

BBOX_PAD_DEG = 0.15  # ~15 km cushion around the member sites


def _load_sites() -> list[dict]:
    sites = json.loads((DATA / "oah_sites.json").read_text(encoding="utf-8"))["sites"]
    au = DATA / "au_sites.json"
    if au.exists():
        sites = sites + json.loads(au.read_text(encoding="utf-8"))["sites"]
    return sites


def _name_regex(waterbody: str) -> str:
    if waterbody in NAME_HINTS:
        return NAME_HINTS[waterbody]
    base = waterbody.split("(")[0].strip()
    for suffix in (" River", " Creek", " Stream"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].strip()
    return base


def _groups(sites: list[dict]) -> dict[str, dict]:
    """waterbody -> {bbox, city, country} from member site coordinates."""
    g: dict[str, dict] = {}
    for s in sites:
        wb = (s.get("waterbody") or "").strip()
        lat, lng = s.get("lat"), s.get("lng")
        if not wb or lat is None or lng is None:
            continue
        rec = g.setdefault(
            wb, {"lat_min": lat, "lat_max": lat, "lng_min": lng, "lng_max": lng,
                 "city": s.get("city"), "country": s.get("country")}
        )
        rec["lat_min"], rec["lat_max"] = min(rec["lat_min"], lat), max(rec["lat_max"], lat)
        rec["lng_min"], rec["lng_max"] = min(rec["lng_min"], lng), max(rec["lng_max"], lng)
    return g


def _query(regex: str, rec: dict, qt: int = 25) -> str:
    s = rec["lat_min"] - BBOX_PAD_DEG
    w = rec["lng_min"] - BBOX_PAD_DEG
    n = rec["lat_max"] + BBOX_PAD_DEG
    e = rec["lng_max"] + BBOX_PAD_DEG
    return (
        f"[out:json][timeout:{qt}];"
        f'(way["waterway"~"river|canal|stream"]["name"~"{regex}",i]'
        f"({s},{w},{n},{e}););out geom;"
    )


def _write(features: list[dict], n_groups: int) -> None:
    fc = {
        "type": "FeatureCollection",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "source": "OpenStreetMap via Overpass API",
        "features": features,
    }
    OUT.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")


async def _overpass(client: httpx.AsyncClient, ql: str) -> list[dict]:
    last_exc: Exception | None = None
    for url in ENDPOINTS:
        try:
            resp = await client.post(
                url, data={"data": ql}, headers={"User-Agent": UA}, timeout=45.0
            )
            if resp.status_code in (429, 504):
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp
                )
                await asyncio.sleep(5.0)
                continue
            resp.raise_for_status()
            return resp.json().get("elements", []) or []
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            await asyncio.sleep(2.0)
    print(f"  ! all Overpass endpoints failed: {last_exc}", file=sys.stderr)
    return []


async def main(only: list[str] | None = None, qt: int = 25) -> None:
    sites = _load_sites()
    groups = _groups(sites)
    # --only wb1,wb2: re-fetch just those waterbodies (e.g. after an Overpass
    # 504) and MERGE into the existing file, keeping every other waterbody's
    # features intact. Useful for the big-bbox EU rivers that sometimes time out.
    features: list[dict] = []
    if only:
        wanted = {w.strip() for w in only}
        groups = {k: v for k, v in groups.items() if k in wanted}
        if OUT.exists():
            existing = json.loads(OUT.read_text(encoding="utf-8")).get("features", [])
            features = [f for f in existing if f["properties"]["waterbody"] not in wanted]
    # EU rivers (the hero courses, multi-site, reliably in OSM) first; then the
    # rest alphabetically. We write the file after every waterbody so a slow or
    # interrupted AU pass still leaves the important rivers bundled.
    order = sorted(groups.items(), key=lambda kv: (kv[0] not in NAME_HINTS, kv[0]))
    async with httpx.AsyncClient() as client:
        for wb, rec in order:
            regex = _name_regex(wb)
            elements = await _overpass(client, _query(regex, rec, qt))
            ways = 0
            for el in elements:
                geom = el.get("geometry") or []
                coords = [[p["lon"], p["lat"]] for p in geom if "lon" in p and "lat" in p]
                if len(coords) < 2:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "waterbody": wb,
                            "name": (el.get("tags") or {}).get("name", wb),
                            "city": rec.get("city"),
                            "country": rec.get("country"),
                            "osm_id": el.get("id"),
                        },
                        "geometry": {"type": "LineString", "coordinates": coords},
                    }
                )
                ways += 1
            print(f"  {wb:16} /{regex:14}/  {ways:3} ways", flush=True)
            _write(features, len(groups))  # incremental: survive interruption
            await asyncio.sleep(1.5)  # respect Overpass slot limits

    print(f"\nwrote {OUT}  ({len(features)} river ways across {len(groups)} waterbodies)")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma-separated waterbodies to re-fetch + merge")
    ap.add_argument("--qt", type=int, default=25, help="Overpass server-side timeout (s)")
    args = ap.parse_args()
    asyncio.run(main(args.only.split(",") if args.only else None, args.qt))
