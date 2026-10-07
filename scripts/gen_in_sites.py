"""Generate data/in_sites.json — a bundled snapshot of REAL Indian river gauging
stations (name + river + WGS84 coordinates) from India-WRIS (National Water
Informatics Centre, Ministry of Jal Shakti).

Same model as data/oah_sites.json (Europe) and data/au_sites.json (Australia):
real station identity + coordinates retrieved once and bundled. These are CWC
surface-water Gauge-Discharge-(Quality) telemetry stations (site_type GDQ/GDSQ),
so — like the Australian BoM set — no ecology/health is claimed; the app shows
the core loop (map · recency · rain · satellite · check · discharge · biodiversity)
for them.

Source: India-WRIS ArcGIS REST, keyless:
  https://arc.indiawris.gov.in/server/rest/services/DataDownload/Telemetry_Stations_Data/MapServer/0
Query filters to surface-water river stations (``river`` set) and returns geometry
in EPSG:4326 (x=lng, y=lat) directly — no reprojection.

Pilot rivers below (south + central India). Extend by adding to RIVERS and re-running:

    python scripts/gen_in_sites.py

Attribution (required): "Data: India-WRIS, National Water Informatics Centre,
Ministry of Jal Shakti (Govt. of India)".
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OUT = Path(__file__).resolve().parent.parent / "data" / "in_sites.json"
COUNTRY = "India"

# Pilot rivers (best telemetry coverage + iconic). Add e.g. "Godavari",
# "Krishna", "Mahanadi" to widen the Indian region — all are in this layer.
RIVERS = ["Cauvery", "Narmada"]

QUERY_URL = (
    "https://arc.indiawris.gov.in/server/rest/services/"
    "DataDownload/Telemetry_Stations_Data/MapServer/0/query"
)
UA = "RiverKin/1.0 (+https://riverkin.online; OneAquaHealth citizen science)"
# India bounding box sanity check (lat, lng).
IN_BBOX = (6.0, 37.5, 68.0, 98.0)


def _clean(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip())
    n = n.replace("@", " at ")
    return n.title()


def _main_stem(river: str) -> str:
    """'Cauvery/Arkavathi' -> 'Cauvery' (the station's main watercourse)."""
    return (river or "").split("/")[0].strip().title() or "River"


def _fetch(river: str) -> list[dict]:
    params = {
        "where": f"river LIKE '{river}%'",
        "outFields": (
            "objectid,site_code_,station_co,site_id,stationnam,site_name,"
            "river,state_name,district_name"
        ),
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultRecordCount": "2000",
    }
    req = Request(f"{QUERY_URL}?{urlencode(params)}", headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as resp:  # noqa: S310 (trusted gov host)
        return json.loads(resp.read().decode("utf-8")).get("features", []) or []


def main() -> None:
    lat0, lat1, lng0, lng1 = IN_BBOX
    seen_codes: set[str] = set()
    seen_pts: set[tuple[float, float]] = set()
    sites: list[dict] = []

    for river in RIVERS:
        feats = _fetch(river)
        kept = 0
        for f in feats:
            a = f.get("attributes", {})
            g = f.get("geometry") or {}
            lng, lat = g.get("x"), g.get("y")
            if lat is None or lng is None:
                continue
            if not (lat0 <= lat <= lat1 and lng0 <= lng <= lng1):
                continue
            raw = a.get("stationnam") or a.get("site_name") or ""
            name = _clean(raw)
            if not name or name.lower() in {"test", "na", "n/a"}:
                continue
            # River stations carry the CWC station code in site_code_/station_co
            # (site_id is null for them); fall back to the stable objectid.
            sid = (
                a.get("site_code_")
                or a.get("station_co")
                or a.get("site_id")
                or a.get("objectid")
            )
            code = f"IN-{sid}"
            pt = (round(lat, 3), round(lng, 3))
            if code in seen_codes or pt in seen_pts:
                continue
            seen_codes.add(code)
            seen_pts.add(pt)
            stem = _main_stem(a.get("river"))
            sites.append(
                {
                    "code": code,
                    "name": name,
                    "waterbody": stem,
                    "city": f"{stem} Basin",
                    "country": COUNTRY,
                    "lat": round(float(lat), 6),
                    "lng": round(float(lng), 6),
                }
            )
            kept += 1
        print(f"  {river:10} -> {kept} stations", flush=True)

    doc = {
        "schema": "riverkin.in_sites.v1",
        "source": (
            "India-WRIS (National Water Informatics Centre, Ministry of Jal Shakti) — "
            "ArcGIS Telemetry_Stations_Data, surface-water CWC gauge stations (GDQ/GDSQ). "
            "Real station ids, names, river and coordinates (EPSG:4326); no ecology/health."
        ),
        "attribution": (
            "Data: India-WRIS, National Water Informatics Centre, "
            "Ministry of Jal Shakti (Govt. of India)"
        ),
        "rivers": RIVERS,
        "count": len(sites),
        "sites": sites,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT} with {len(sites)} sites across {len(RIVERS)} rivers")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
