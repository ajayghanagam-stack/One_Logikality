"""Temporal worker entrypoint.

Phase 0: connects to Temporal and idles — no workflows or activities registered.
Real ECV workflows (OCR → Classify → Extract → Validate → Analyze) land in
Step 4 (Phase 3) per docs/Plan.md.

Run natively: ``python -m app.pipeline.worker`` (from backend/ with venv active).
"""

from __future__ import annotations

import asyncio
import logging

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.config import settings

log = logging.getLogger(__name__)

TASK_QUEUE = "ecv"  # per docs/TechStack.md §5; one queue per micro-app


@activity.defn(name="_phase0_noop")
async def _phase0_noop() -> None:
    """Placeholder so Worker() can instantiate before real activities exist.

    Temporal requires at least one activity / workflow / Nexus service
    registered on a Worker. Remove this in Step 4 (Phase 3) when the real
    ECV activities (OCR, Classify, Extract, Validate, Analyze) are added.
    """


async def run() -> None:
    log.info("Connecting to Temporal at %s", settings.temporal_address)
    client = await Client.connect(settings.temporal_address)
    worker = Worker(client, task_queue=TASK_QUEUE, activities=[_phase0_noop])
    log.info(
        "Temporal worker idling on task queue %r (placeholder noop registered; "
        "real ECV activities land in Step 4)",
        TASK_QUEUE,
    )
    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run())
