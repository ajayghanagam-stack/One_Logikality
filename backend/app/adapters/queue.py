"""Pipeline queue driver abstraction per docs/TechStack.md §5, §15.

Implementations (later phases):
- TemporalQueue           PIPELINE_BACKEND=temporal           (default)
- BackgroundTasksQueue    PIPELINE_BACKEND=background_tasks   (degraded fallback)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class QueueAdapter(ABC):
    @abstractmethod
    async def submit(self, workflow_name: str, *, args: dict[str, Any]) -> str:
        """Submit a workflow run. Returns a provider-specific run identifier."""

    @abstractmethod
    async def status(self, run_id: str) -> str:
        """Return a coarse workflow status string (running / completed / failed)."""
