"""Scheduled job entrypoint: rain pull + site need recompute.

Run locally with::

    python -m app.jobs.scheduled

In production this is invoked by an Azure Container Apps cron Job every 3 h.
Stub only — no network calls yet.
"""

from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.jobs.scheduled")


def main() -> None:
    """Pull rain data and recompute per-site need scores.

    TODO(PRD): fetch Open-Meteo rainfall for each site's catchment, then
    recompute N_s via app.scoring.need_score and persist. Must be idempotent
    (API runs at 1 replica so this never races a second run).
    """
    logger.info("rain pull + need recompute — TODO(PRD), no-op stub")


if __name__ == "__main__":
    main()
