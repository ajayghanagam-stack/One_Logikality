"""Local filesystem implementation of `StorageAdapter`.

Writes under `settings.storage_path`. Keys can include slashes and are
treated as relative paths (e.g. `packets/<org_id>/<packet_id>/foo.pdf`);
any required parent directories are created on write. This is the
development / Docker-compose default — swap to `S3Storage` in staging
and production by flipping `STORAGE_PROVIDER`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.adapters.storage import StorageAdapter
from app.config import settings


class LocalFilesystemStorage(StorageAdapter):
    def __init__(self, base_path: str | None = None) -> None:
        self._base = Path(base_path or settings.storage_path).resolve()

    def _resolve(self, key: str) -> Path:
        # Block absolute keys and `..` traversal — this adapter takes the
        # key from callers that compose it themselves (org_id / packet_id),
        # but defense-in-depth matters if a future caller ever plumbs user
        # input into it.
        candidate = (self._base / key).resolve()
        if not str(candidate).startswith(str(self._base)):
            raise ValueError(f"invalid storage key: {key!r}")
        return candidate

    async def put(self, key: str, data: bytes) -> str:
        target = self._resolve(key)

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        await asyncio.to_thread(_write)
        return f"file://{target}"

    async def get(self, key: str) -> bytes:
        target = self._resolve(key)
        return await asyncio.to_thread(target.read_bytes)

    async def delete(self, key: str) -> None:
        target = self._resolve(key)

        def _delete() -> None:
            try:
                target.unlink()
            except FileNotFoundError:
                pass

        await asyncio.to_thread(_delete)


def get_storage() -> StorageAdapter:
    """Factory — reads `STORAGE_PROVIDER` to decide which impl to return.

    Kept as a tiny function rather than a module-level singleton so tests
    can override `settings.storage_path` and get a fresh adapter without
    monkey-patching. S3 wiring lands in a later phase.
    """
    if settings.storage_provider == "local":
        return LocalFilesystemStorage()
    raise NotImplementedError(f"storage provider {settings.storage_provider!r} not yet implemented")
