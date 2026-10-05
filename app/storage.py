"""Durable photo storage in Azure Blob (shared across replicas, survives restarts).

Authenticated with the Container App's managed identity via
``DefaultAzureCredential`` — no account keys or SAS secrets in the app. Falls
back to local disk (``media/``) when ``STORAGE_ACCOUNT_URL`` is unset, so local
dev and CI need no cloud. Blob and disk use the same flat object name
(``obs00015-water.jpg``) so either path serves the same photo.

These are synchronous SDK calls; the routers invoke them via
``run_in_threadpool`` so the event loop is never blocked.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import settings

logger = logging.getLogger("app.storage")


def enabled() -> bool:
    return bool(settings.STORAGE_ACCOUNT_URL)


@lru_cache(maxsize=1)
def _container():
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    service = BlobServiceClient(
        settings.STORAGE_ACCOUNT_URL, credential=DefaultAzureCredential()
    )
    return service.get_container_client(settings.PHOTO_CONTAINER)


def upload(name: str, data: bytes) -> bool:
    """Upload processed JPEG bytes under ``name``. Returns True on success."""
    try:
        from azure.storage.blob import ContentSettings

        _container().upload_blob(
            name,
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type="image/jpeg"),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("blob upload failed for %s: %s", name, exc)
        return False


def download(name: str) -> bytes | None:
    """Fetch the blob bytes, or None if missing/unavailable."""
    try:
        return _container().download_blob(name).readall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("blob download failed for %s: %s", name, exc)
        return None
