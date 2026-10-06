"""Generate data/au_sites.json — a bundled snapshot of REAL Australian river
monitoring stations (name + WGS84 coordinates) from the Bureau of Meteorology's
national Water Data Online service (OGC SOS2 / WaterML2).

This mirrors how data/oah_sites.json was produced for Europe: real station
identity + coordinates retrieved once and bundled. No water-quality/ecology is
claimed for these sites (BoM coverage is mostly level/discharge), so the app
shows the core loop (map · recency · rain · satellite · check) for them and
omits the ecosystem panel.

Pilot region: Melbourne (bbox below). Run manually when refreshing/extending:

    # 1) download the national feature list once (~80 MB) from:
    #    bom.gov.au/waterdata/services?service=SOS&version=2.0&request=GetFeatureOfInterest
    curl -A "Mozilla/5.0" "<that URL>" -o bom_all.xml
    # 2) generate:
    python scripts/gen_au_sites.py bom_all.xml
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "au_sites.json"

# Pilot city + bounding box (lat_min, lat_max, lng_min, lng_max).
CITY = "Melbourne"
COUNTRY = "Australia"
BBOX = (-38.2, -37.4, 144.5, 145.6)
MAX_SITES = 16

# Extract each MonitoringPoint as a self-contained block first, THEN pull its
# id/name/pos — so coordinates can never be mismatched across stations.
_POINT = re.compile(r"<wml2:MonitoringPoint\b.*?</wml2:MonitoringPoint>", re.S)
_ID = re.compile(r'stations/([^<"]+)</gml:identifier')
_NAME = re.compile(r"<gml:name>([^<]*)</gml:name>")
_POS = re.compile(r"<gml:pos[^>]*>([-\d.]+)\s+([-\d.]+)</gml:pos>")


def _clean(raw: str) -> str:
    n = raw.strip().replace("@", " at ")
    n = re.sub(r"\s*-\s*", " - ", n)  # normalise the location separator
    n = re.sub(r"\bCK\b", "Creek", n, flags=re.I)
    n = re.sub(r"\bRV\b", "River", n, flags=re.I)
    n = re.sub(r"\bU/S\b", "upstream", n, flags=re.I)
    n = re.sub(r"\bD/S\b", "downstream", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip()
    return n.title()


def _waterbody(name: str) -> str:
    """The watercourse itself, e.g. 'Yarra River At Yering' -> 'Yarra River'."""
    m = re.match(r"^(.*?\b(?:River|Creek|Ck))\b", name, re.I)
    if m:
        return m.group(1).strip()
    return re.split(r"—| at ", name)[0].strip() or name


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not src or not src.exists():
        raise SystemExit("usage: python scripts/gen_au_sites.py <bom_feature_list.xml>")
    xml = src.read_text(encoding="utf-8", errors="replace")

    lat0, lat1, lng0, lng1 = BBOX
    seen: set[str] = set()
    seen_pts: set[tuple[float, float]] = set()
    sites: list[dict] = []

    # Parse each station block into (id, name, lat, lng).
    parsed: list[tuple[str, str, float, float]] = []
    for block in _POINT.findall(xml):
        mid, mname, mpos = _ID.search(block), _NAME.search(block), _POS.search(block)
        if not (mid and mname and mpos):
            continue
        try:
            lat, lng = float(mpos.group(1)), float(mpos.group(2))
        except ValueError:
            continue
        parsed.append((mid.group(1), mname.group(1), lat, lng))

    # Prefer named Rivers first, then Creeks, for recognisable demo content.
    def key(m: tuple[str, str, float, float]) -> int:
        name = m[1].lower()
        return 0 if "river" in name else 1 if ("ck" in name or "creek" in name) else 2

    for sid, raw, lat, lng in sorted(parsed, key=key):
        if not (lat0 <= lat <= lat1 and lng0 <= lng <= lng1):
            continue
        if not re.search(r"\b(River|Creek|Ck|Rv)\b", raw, re.I):
            continue
        name = _clean(raw)
        wb = _waterbody(name)
        # Drop malformed captures (e.g. "Arthurs C - Arthurs Creek").
        if " - " in wb or len(wb.split()) > 3:
            continue
        base = wb.lower()
        pt = (round(lat, 3), round(lng, 3))
        if base in seen or pt in seen_pts:  # one station per river / per point
            continue
        seen.add(base)
        seen_pts.add(pt)
        sites.append(
            {
                "code": f"AU-{sid}",
                "name": name,
                "waterbody": wb,
                "city": CITY,
                "country": COUNTRY,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
            }
        )
        if len(sites) >= MAX_SITES:
            break

    doc = {
        "schema": "riverkin.au_sites.v1",
        "source": (
            "Bureau of Meteorology — Water Data Online (OGC SOS2/WaterML2), "
            "GetFeatureOfInterest. Real station codes, names and coordinates; "
            "no ecology/health data (BoM coverage is level/discharge)."
        ),
        "attribution": "Data: Bureau of Meteorology (Water Data Online)",
        "city": CITY,
        "count": len(sites),
        "sites": sites,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} with {len(sites)} sites")
    for s in sites:
        print(f"  {s['code']:14} {s['name']}")


if __name__ == "__main__":
    main()
