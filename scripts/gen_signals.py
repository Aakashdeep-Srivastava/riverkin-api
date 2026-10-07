"""Generate data/site_signals.json — a one-time snapshot of the keyless open-data
signals (GBIF freshwater bioindicator richness + GloFAS river discharge) for every
bundled site, keyed by external_id.

This mirrors how data/oah_sites.json and data/au_sites.json were produced: real
data retrieved once and bundled, so a fresh deploy serves real signals before the
first scheduled refresh. The scheduled job (app/jobs/scheduled.py) keeps the values
current in the DB; app/seed.py only fills from this bundle when a column is still
empty (COALESCE), so re-seeding never clobbers fresher cron data.

Both sources are keyless and degrade to null on failure — a partial run is fine
(the cron fills the rest). Run manually when refreshing:

    python scripts/gen_signals.py          # all bundled sites
    python scripts/gen_signals.py --limit 5  # quick smoke test

Attribution: "Powered by GBIF (GBIF.org)" and "Flood data by Open-Meteo.com
(CC-BY 4.0); source GloFAS/Copernicus (ECMWF)".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import signals  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "site_signals.json"


def _load_sites() -> list[dict]:
    sites = json.loads((DATA / "oah_sites.json").read_text(encoding="utf-8"))["sites"]
    for extra in ("au_sites.json", "in_sites.json"):
        p = DATA / extra
        if p.exists():
            sites = sites + json.loads(p.read_text(encoding="utf-8"))["sites"]
    return sites


async def _one(client: httpx.AsyncClient, lat: float, lng: float) -> dict:
    bio = await signals.fetch_biodiversity(client, lat, lng)
    dis = await signals.fetch_discharge(client, lat, lng)
    return {"biodiversity": bio, "discharge": dis}


async def main(limit: int | None) -> None:
    sites = _load_sites()
    if limit:
        sites = sites[:limit]
    out: dict[str, dict] = {}
    async with httpx.AsyncClient() as client:
        for i, s in enumerate(sites, 1):
            code = s.get("oah_code") or s["code"]
            lat, lng = s.get("lat"), s.get("lng")
            if lat is None or lng is None:
                continue
            sig = await _one(client, lat, lng)
            out[code] = sig
            bio = sig["biodiversity"]
            dis = sig["discharge"]
            bio_txt = f"{bio['species_richness']} sp" if bio else "—"
            dis_txt = f"{dis['latest_m3s']:.1f} m3s" if dis else "—"
            print(
                f"[{i}/{len(sites)}] {code} {s.get('name', '')[:28]:28} "
                f"bio={bio_txt:>7} q={dis_txt:>9}",
                flush=True,
            )
            await asyncio.sleep(0.4)  # polite to both free APIs
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    have_bio = sum(1 for v in out.values() if v["biodiversity"])
    have_dis = sum(1 for v in out.values() if v["discharge"])
    print(f"\nwrote {OUT}  ({len(out)} sites; {have_bio} with GBIF, {have_dis} with GloFAS)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    asyncio.run(main(args.limit))
