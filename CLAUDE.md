# RiverKin API — instructions for Claude Code

RiverKin is our Track 5 entry for the IEEE OneAquaHealth Global Hackathon 2026.
Deadline: Oct 4, 2026, 21:00 PDT (Oct 5, 09:30 IST). Ship a working, deployed loop over extra features.

The full product spec is in `docs/PRD.md`. This repo is the **backend only**.
Frontend lives in a separate repo: https://github.com/Aakashdeep-Srivastava/riverkin-web

## Read these PRD sections before any work
Data model, API specification, Algorithms, AI service, FHIR export, Security/privacy/safety,
Non-functional requirements and testing. Treat the PRD as the source of truth; ask before deviating.

## Scope: the "Perfect 6" (build in this order)
1. `GET /sites`, `GET /sites/{id}` with need score (seed the bundled OAH site list, 106 sites)
2. Open-Meteo rain pull + site need score N_s (`app/scoring.py`)
3. `POST /observations` + photo upload (blur, pHash, EXIF strip, face blur)
4. Verify rounds: `GET /verify/next`, `POST /verify/{item_id}/vote`, gold items, trust scoring
5. Receipt + status: `GET /observations/{id}/status`
6. FHIR Bundle export (Observation + Provenance) to HAPI, `GET /fhir/observations/{id}`, expert queue
Everything else (crews, check-ins, missions engine, metrics) comes only after these pass tests.

## Stack
Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, PostgreSQL 16 + PostGIS,
`uv` for dependencies, `fhir.resources` (R4), OpenCV + imagehash, `azure-storage-blob` + `azure-identity`.
MVP background work: FastAPI BackgroundTasks. Scheduled work: `python -m app.jobs.scheduled`
(run by an Azure Container Apps cron Job every 3 h). No Celery/Redis for the MVP.

## Layout
```
app/main.py            FastAPI app, CORS, /healthz, /api/v1 routers
app/config.py          pydantic-settings; every setting from env vars
app/db.py              async engine/session
app/models/            SQLAlchemy models (PRD Data model)
app/routers/           sites, observations, verify, expert, fhir, auth
app/scoring.py         PURE functions: need, value, reliability, trust (no I/O)
app/ai/questions.py    VLM question generation + deterministic fallback
app/fhir/bundle.py     Bundle builder shaped to the OAH IG
app/jobs/scheduled.py  rain pull + need recompute
data/oah_sites.json    bundled site list (credit OneAquaHealth in README)
alembic/               migrations; first migration runs CREATE EXTENSION postgis
tests/                 pytest; scoring.py coverage >= 90%
```

## Environment variables (never hard-code; keep `.env.example` updated)
`DATABASE_URL`, `JWT_SECRET`, `CORS_ORIGINS` (comma list), `STORAGE_ACCOUNT_URL`, `PHOTO_CONTAINER`,
`FHIR_BASE_URL`, `VLM_PROVIDER` (`none`|`moondream`|`hosted`), `VLM_API_KEY` (optional), `APP_ENV`.
Locally use `.env` (git-ignored). In Azure, secrets come from Key Vault references.

## Hard rules
- AI asks, humans decide: the model only writes verify questions and a weak prior. It never fills a field.
- No points per submission, no leaderboard. Rewards follow the PRD value formula.
- Safety refusals return 403 + `safety_reason`. No raw GPS stored after the geofence check.
- Any simulated data is flagged `simulated=true` and labelled in responses that expose it.
- The OpenAPI schema is the contract with the frontend. Do not break `/api/v1` shapes silently;
  update `openapi.json` (exported by `scripts/export_openapi.py`) in the same PR.
- No secrets, keys or real personal data in commits, logs or test fixtures.

## Docker
Multi-stage `Dockerfile` on `python:3.12-slim`, non-root user, listens on port 8000.
Entrypoint: `alembic upgrade head` then `uvicorn app.main:app --host 0.0.0.0 --port 8000`
(keep API at 1 replica during the hackathon so migrations never run twice).
Add `docker-compose.yml` for local dev: api, postgis/postgis:16-3.4, hapiproject/hapi.

## CI/CD (`.github/workflows/ci-cd.yml`, already provided)
PR: ruff, alembic upgrade on a PostGIS service container, pytest.
Push to main: build in Azure Container Registry, update the Container App and the cron Job, smoke-test `/healthz`.
Do not change the workflow's auth model (OIDC via `azure/login`); never add cloud passwords as secrets.

## Definition of done for a feature
Endpoint implemented per PRD, tests pass, `.env.example` and `openapi.json` updated, README section updated.
