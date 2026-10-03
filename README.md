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

## Credits

- **Sites:** monitoring sites are based on the [OneAquaHealth](https://oneaquahealth.eu)
  project (IEEE OneAquaHealth). The bundled `data/oah_sites.json` currently holds
  **simulated** placeholder sites (`simulated: true`) pending the real 106-site list.
- **Weather:** rainfall data via [Open-Meteo](https://open-meteo.com).

Any simulated data in this repo is flagged `simulated=true` and labelled in
responses that expose it.
