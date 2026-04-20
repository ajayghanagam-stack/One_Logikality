"""Storage driver abstraction per docs/TechStack.md §7, §15.

Implementations (later phases):
- LocalFilesystemStorage  STORAGE_PROVIDER=local  (default; writes to STORAGE_PATH)
- S3Storage               STORAGE_PROVIDER=s3     (S3_ENDPOINT + bucket + keys)
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class StorageAdapter(ABC):
    @abstractmethod
    async def put(self, key: str, data: bytes) -> str:
        """Store ``data`` under ``key``. Returns the storage-relative URI."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Fetch bytes stored under ``key``. Raises if absent."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete object under ``key``. No-op if absent."""
