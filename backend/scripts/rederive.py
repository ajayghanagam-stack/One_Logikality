"""One-shot script to re-derive micro-app findings for all completed packets.

Usage (from the backend/ directory):
    python -m scripts.rederive

Run this after deploying the new AI-pipeline modules to populate
title-exam, income, compliance, and title-search findings from the
already-classified and already-extracted document data.

The script is idempotent: each derivation module short-circuits if findings
already exist for a packet, so it is safe to run multiple times.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid

# Ensure the backend package is on sys.path when run as a module.
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Packet
from app.pipeline.compliance_pipeline import derive_compliance
from app.pipeline.income_pipeline import derive_income
from app.pipeline.title_exam_pipeline import derive_title_exam
from app.pipeline.title_search_pipeline import derive_title_search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("rederive")


async def _rederive_packet(packet_id: uuid.UUID) -> None:
    log.info("rederive: processing packet %s", packet_id)
    await asyncio.gather(
        derive_title_exam(packet_id),
        derive_income(packet_id),
        derive_compliance(packet_id),
        derive_title_search(packet_id),
    )
    log.info("rederive: done with packet %s", packet_id)


async def main() -> None:
    async with SessionLocal() as session:
        packets = (
            (
                await session.execute(
                    select(Packet.id).where(Packet.status == "completed").order_by(Packet.id)
                )
            )
            .scalars()
            .all()
        )

    if not packets:
        log.info("rederive: no completed packets found")
        return

    log.info("rederive: found %d completed packet(s)", len(packets))
    for packet_id in packets:
        await _rederive_packet(packet_id)

    log.info("rederive: all done")


if __name__ == "__main__":
    asyncio.run(main())
