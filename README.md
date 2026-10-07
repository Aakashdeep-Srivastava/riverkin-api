# RiverKin API

Backend for **RiverKin**, our Track 5 entry for the IEEE OneAquaHealth Global
Hackathon 2026. This repo is the **backend only**. The web frontend lives in a
separate repo: https://github.com/Aakashdeep-Srivastava/riverkin-web

RiverKin turns citizen water observations into verified, FHIR-exportable
signals for river health, prioritising where observations are most needed.

> Status: **Perfect 6 complete + crews/timeline.** The full citizen loop is
> real end to end — sites & need scoring, `POST /observations` (geofence, photo
> blur/pHash/EXIF, quality), verify rounds with log-odds trust, impact receipts,
> OAH-shaped FHIR R4 Bundles, expert queue/review, metrics, and crew setup.
> 56 pytest + 6 Playwright E2E pass against Postgres+PostGIS. Still open: auth/RBAC
> (endpoints are open for the demo), missions engine, and the HL7 IG validator in CI.

## Stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic ·
PostgreSQL 16 + PostGIS · `uv` · `fhir.resources` (R4) · OpenCV + imagehash ·
Azure Blob storage.

## The "Perfect 6" (build order)

1. `GET /sites`, `GET /sites/{id}` with need score
2. Open-Meteo rain pull + site need score (`app/scoring.py`)
3. `POST /observations` + photo upload (blur, pHash, EXIF strip, face blur)
4. Verify rounds: `GET /verify/next`, `POST /verify/{item_id}/vote`, trust scoring
5. Receipt + status: `GET /observations/{id}/status`
6. FHIR Bundle export (Observation + Provenance), expert queue

**Photo pipeline:** `POST /observations/{id}/photos` (multipart `file`, `kind`,
`captured_live`) strips EXIF, scores blur (422 retake), blurs faces, rejects
pHash duplicates (409), then runs a small **Azure AI Foundry vision model**
(`app/ai/vision.py`; deterministic heuristic fallback when `FOUNDRY_VISION_*`
is unset) for a scene summary + AI-generated estimate, and a combined
**capture-authenticity** score (`app/authenticity.py`: live-capture + EXIF +
pHash novelty + model estimate). The processed image is served from
`GET /observations/{id}/photo` and summarised on the receipt, geotagged with the
site's coarse location (never raw device GPS).

Later layers (after the Perfect 6): crews & check-ins, site timeline, metrics,
auth (guest + Microsoft OIDC), and the **missions engine** —
`GET /missions` (suggested field missions, most-urgent first, `?city=` filter)
and `GET /missions/{oah_code}` (the C3 brief). Missions are derived live from the
seeded OAH sites using the same need/attention scoring plus the typing rules in
`app/missions.py` (flag follow-up · after-the-rain · orphan · cadence · monitoring).

## Local development

### With Docker Compose (API + PostGIS + HAPI FHIR)

```bash
cp .env.example .env     # adjust if needed
docker compose up --build
# API:  http://localhost:8000  (docs at /docs, health at /healthz)
# FHIR: http://localhost:8080/fhir
```

### With uv (API against your own Postgres/PostGIS)

```bash
uv sync                               # install deps into .venv
cp .env.example .env                  # set DATABASE_URL etc.
uv run alembic upgrade head           # create schema (needs PostGIS)
uv run uvicorn app.main:app --reload  # serve on :8000
```

### Tests & lint

```bash
uv run ruff check .
uv run pytest -q
```

### Regenerate the OpenAPI contract

The OpenAPI schema is the contract with the frontend — regenerate and commit
`openapi.json` whenever an `/api/v1` shape changes:

```bash
uv run python scripts/export_openapi.py
```

### Scheduled job (rain pull + need recompute)

```bash
uv run python -m app.jobs.scheduled
```

## Environment variables

See [`.env.example`](.env.example). Summary:

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `local` \| `test` \| `production` |
| `DATABASE_URL` | async SQLAlchemy / asyncpg URL |
| `JWT_SECRET` | JWT signing secret |
| `CORS_ORIGINS` | comma-separated allowed origins |
| `STORAGE_ACCOUNT_URL` | Azure Blob account URL for photos |
| `PHOTO_CONTAINER` | Blob container for processed photos |
| `FHIR_BASE_URL` | HAPI FHIR server base URL |
| `VLM_PROVIDER` | `none` \| `moondream` \| `hosted` |
| `VLM_API_KEY` | optional, only for non-`none` providers |

Never commit a real `.env` or any secret. In Azure, secrets come from Key Vault
references.

## Real open-data signals

Beyond the OAH baseline, each site is enriched with keyless open data, cached on
the site row by the scheduled job (`app/signals.py`) and served without a live
upstream call. Regenerate the bundled one-time snapshots with:

```bash
uv run python scripts/gen_signals.py   # data/site_signals.json (GBIF + GloFAS)
uv run python scripts/gen_rivers.py    # data/rivers.geojson (OSM via Overpass)
```

- **Biodiversity** — GBIF freshwater bioindicator richness (EPT + amphibians)
  within 5 km of each site (`GET /sites` → `biodiversity`).
- **River discharge** — GloFAS daily discharge m³/s with a 30-day series
  (`GET /sites` → `discharge`).
- **River geometry** — real OSM river courses as GeoJSON (`GET /maps/rivers`).

## Credits

- **Sites, ecology & One Health risk:** [OneAquaHealth](https://oneaquahealth.eu)
  project (IEEE OneAquaHealth) — real coordinates/identity/baseline from
  api.enora-oah.eu (see `data/DATA_PROVENANCE.md`). Only the "days since last
  citizen check" schedule is illustrative and flagged `recency_simulated`.
- **Weather:** rainfall via [Open-Meteo](https://open-meteo.com) (CC-BY 4.0).
- **Biodiversity:** Powered by [GBIF](https://www.gbif.org) (GBIF.org).
- **River discharge:** [Open-Meteo Flood API](https://open-meteo.com) (CC-BY 4.0),
  source GloFAS/Copernicus (ECMWF).
- **River geometry:** © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors (ODbL).

Any simulated data in this repo is flagged `simulated=true` and labelled in
responses that expose it.
