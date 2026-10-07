"""Application settings, loaded from environment variables (see .env.example).

Every value here maps to an env var documented in CLAUDE.md. Locally these come
from a git-ignored `.env`; in Azure they come from Key Vault references.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    APP_ENV: Literal["local", "test", "production"] = "local"

    # Database (async SQLAlchemy / asyncpg URL).
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/riverkin"
    )

    # Auth
    JWT_SECRET: str = "dev-only-not-a-secret"

    # CORS — comma-separated list of allowed origins.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # Azure Blob storage for observation photos.
    STORAGE_ACCOUNT_URL: str = ""
    PHOTO_CONTAINER: str = "photos"

    # FHIR (HAPI server base URL).
    FHIR_BASE_URL: str = "http://localhost:8080/fhir"

    # VLM provider for verify-question generation.
    VLM_PROVIDER: Literal["none", "moondream", "hosted"] = "none"
    VLM_API_KEY: str | None = None

    # Azure AI Foundry — small, low-cost vision model for photo analysis +
    # AI-generated likelihood. Empty endpoint/key → deterministic fallback is
    # used (the flow always works; the real model activates once these are set).
    FOUNDRY_VISION_ENDPOINT: str = ""  # e.g. https://<resource>.services.ai.azure.com/models
    FOUNDRY_VISION_KEY: str = ""
    FOUNDRY_VISION_MODEL: str = "Phi-3.5-vision-instruct"
    FOUNDRY_API_VERSION: str = "2024-05-01-preview"

    # Microsoft (Entra) OIDC for adult sign-in. Empty disables the button.
    MS_CLIENT_ID: str = ""
    MS_CLIENT_SECRET: str = ""
    MS_TENANT: str = "common"  # common = any Microsoft account (org + personal)
    MS_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/microsoft/callback"
    # Where to send the browser back after a successful sign-in.
    WEB_URL: str = "http://localhost:3000"

    # Strava OAuth for linking a runner's activities to their account. Empty
    # disables the "Connect Strava" button (same gating as Microsoft above).
    STRAVA_CLIENT_ID: str = ""
    STRAVA_CLIENT_SECRET: str = ""
    STRAVA_REDIRECT_URI: str = "http://localhost:8000/api/v1/strava/callback"

    # Geofence enforcement. When True, a check logged outside the site radius is
    # refused (403). When False (default — demo/field-test friendly), the check
    # is accepted but flagged ``geom_ok=False`` ("location not verified") so the
    # full pipeline (GPT vision + authenticity) still runs from anywhere and the
    # receipt reports honestly whether the visitor was confirmed at the site.
    GEOFENCE_ENFORCE: bool = False

    # TTL (seconds) for the in-process GET /sites response cache. The site list
    # is identical for every viewer and only changes when the 3-hourly job
    # recomputes need scores, so memoising the built list for a short window
    # removes the per-request table scan + per-row scoring (the hot path). Also
    # drives the public Cache-Control max-age so browsers/CDN can cache. 0 = off.
    SITES_CACHE_TTL: int = 60

    # Role-based access control. When True (default), privileged endpoints (the
    # expert review queue + decisions) require a bearer token whose user has the
    # right role (401 if unauthenticated, 403 if under-privileged). Set False to
    # restore the fully-open demo behaviour. Mirrors GEOFENCE_ENFORCE.
    RBAC_ENFORCE: bool = True

    # Azure Maps — the account uniqueId (client id). Used to mint AAD tokens for
    # the browser via managed identity; not a secret.
    AZURE_MAPS_CLIENT_ID: str = ""

    # Web Push (VAPID). PUBLIC is the browser applicationServerKey (not secret);
    # PRIVATE_B64 is base64(PKCS8 PEM) and IS a secret. Empty → push disabled.
    VAPID_PUBLIC: str = ""
    VAPID_PRIVATE_B64: str = ""
    VAPID_SUBJECT: str = "mailto:hello@riverkin.online"

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS parsed into a clean list."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (safe to import anywhere)."""
    return Settings()


settings = get_settings()
