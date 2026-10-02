"""Seed the sites table from the bundled OneAquaHealth site list.

Run once at deploy (Docker CMD) and safe to re-run (idempotent upsert on the
OAH code). Reads ``data/oah_sites.json`` — 106 real OAH sites across the five
research cities; see data/DATA_PROVENANCE.md. Because OAH has not published
real last-check dates, we synthesize a deterministic spread so the attention
map is "alive"; every seeded row is flagged ``simulated=True``.

    python -m app.seed
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from geoalchemy2 import WKTElement
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app import scoring
from app.db import SessionLocal
from app.models.site import Site

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.seed")

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "oah_sites.json"

# Deterministic spread of "days since last verified check" so the map shows a
# realistic mix of fresh, attention, urgent and orphan (>=30 d) sites.
_DAYS_PATTERN = [0, 1, 2, 3, 5, 8, 12, 16, 19, 23, 26, 31, 40, 7, 4, 10, 14, 2, 6, 9, 17, 28]


def _synthesize(index: int, cadence: int) -> dict:
    """Deterministic scoring inputs for one seeded site."""
    days = _DAYS_PATTERN[index % len(_DAYS_PATTERN)]
    rain = 24.0 if index % 7 == 0 else float((index % 5) * 3)
    flag = index % 23 == 0 and days >= 5
    visit_share = max(0.0, 1.0 - days / 42.0)
    need = scoring.need_score(
        float(days),
        cadence_days=float(cadence),
        visit_share_90d=visit_share,
        rain_48h_mm=rain,
        expert_flag_open=flag,
    )
    return {
        "days": days,
        "rain": rain,
        "flag": flag,
        "need": need,
        "last_verified_at": datetime.now(UTC) - timedelta(days=days),
    }


def _rows() -> list[dict]:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    sites = data["sites"]
    rows: list[dict] = []
    for i, s in enumerate(sites):
        cadence = int(s.get("cadence_days", 14))
        syn = _synthesize(i, cadence)
        rows.append(
            {
                "external_id": s["oah_code"],
                "name": s["name"],
                "waterbody": s.get("waterbody"),
                "city": s.get("city"),
                "country": s.get("country"),
                "lat": s["lat"],
                "lng": s["lng"],
                "location": WKTElement(f"POINT({s['lng']} {s['lat']})", srid=4326),
                "cadence_days": cadence,
                "last_verified_at": syn["last_verified_at"],
                "rain_48h_mm": syn["rain"],
                "expert_flag_open": syn["flag"],
                "need_score": syn["need"],
                "simulated": True,
            }
        )
    return rows


async def seed() -> int:
    """Upsert every bundled site. Returns the number of rows processed."""
    rows = _rows()
    async with SessionLocal() as session:
        for row in rows:
            stmt = insert(Site).values(**row)
            update_cols = {
                c: getattr(stmt.excluded, c)
                for c in (
                    "name",
                    "waterbody",
                    "city",
                    "country",
                    "lat",
                    "lng",
                    "location",
                    "cadence_days",
                    "last_verified_at",
                    "rain_48h_mm",
                    "expert_flag_open",
                    "need_score",
                    "simulated",
                )
            }
            update_cols["updated_at"] = func.now()
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"], set_=update_cols
            )
            await session.execute(stmt)
        await session.commit()
    logger.info("seeded %d OAH sites", len(rows))
    return len(rows)


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
