"""ECV pipeline orchestrator (US-3.4).

Walks a packet through the processing stages, updating its row after each
stage. Every stage that does real work calls the appropriate pipeline module
rather than seeding canned data.

Stage order: ingest → classify → extract → validate → score → route

- classify: Gemini 2.5 Flash classifies every page into MISMO 3.6 doc types
- extract: Gemini 2.5 Pro extracts MISMO 3.6 fields from each classified doc
- validate: Claude Sonnet evaluates the 13-section ECV check set
- score: derives micro-app findings (title-exam, income, compliance,
         title-search) from the real classified/extracted data

All micro-app derivation stages are idempotent and failure-tolerant: a
Claude timeout or empty-text document leaves that micro-app's DB tables empty
rather than aborting the pipeline. The frontend renders an appropriate empty
state when tables are empty.

Scheduled as a FastAPI BackgroundTask from POST /api/packets; runs after
the response is sent. Tests monkeypatch STAGE_DELAY_SECONDS to ~0 and stub
classify/extract/validate/derive calls so the polling loop terminates fast.

Background tasks don't carry request auth context, so writes go through the
default connection role (postgres superuser in local dev), bypassing RLS
intentionally — this is server-internal orchestration.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import EcvDocument, EcvSection, Packet
from app.pipeline.classify import classify_packet
from app.pipeline.compliance_pipeline import derive_compliance
from app.pipeline.confirm import confirm_program
from app.pipeline.extract import extract_packet
from app.pipeline.income_pipeline import derive_income
from app.pipeline.title_exam_pipeline import derive_title_exam
from app.pipeline.title_search_pipeline import derive_title_search
from app.pipeline.validate import validate_packet

log = logging.getLogger(__name__)

# Ordered, frozen — consumed by both the runner and the migration 0007
# CHECK constraint. If this tuple changes, migration 0007 needs a follow-up.
PIPELINE_STAGES: tuple[str, ...] = (
    "ingest",
    "classify",
    "extract",
    "validate",
    "score",
    "route",
)

# Per-stage wall-clock delay. Real work dominates total time; this small
# sleep gives the PipelineProgress component visible stage ticks without
# adding meaningful latency. Tests monkeypatch to ~0.01s.
STAGE_DELAY_SECONDS: float = 0.1


async def run_ecv_stub(packet_id: uuid.UUID) -> None:
    """Walk a packet through the pipeline stages.

    Flips to `processing` + `started_processing_at`, runs each stage in
    order, then flips to `completed` + `completed_at`. Any unhandled
    exception flips the packet to `failed`.
    """
    try:
        started = datetime.now(UTC)
        async with SessionLocal() as session:
            await session.execute(
                update(Packet)
                .where(Packet.id == packet_id)
                .values(status="processing", started_processing_at=started)
            )
            await session.commit()

        for stage in PIPELINE_STAGES:
            async with SessionLocal() as session:
                await session.execute(
                    update(Packet).where(Packet.id == packet_id).values(current_stage=stage)
                )
                await session.commit()

            if stage == "classify":
                await _run_classify(packet_id)
            elif stage == "extract":
                await _run_extract(packet_id)
            elif stage == "validate":
                await _run_validate(packet_id)
            elif stage == "score":
                await _run_score(packet_id)

            await asyncio.sleep(STAGE_DELAY_SECONDS)

        async with SessionLocal() as session:
            await session.execute(
                update(Packet)
                .where(Packet.id == packet_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await session.commit()

    except Exception:
        log.exception("ECV pipeline failed for packet %s", packet_id)
        try:
            async with SessionLocal() as session:
                await session.execute(
                    update(Packet).where(Packet.id == packet_id).values(status="failed")
                )
                await session.commit()
        except Exception:
            log.exception("also failed to mark packet %s as failed", packet_id)


async def _run_classify(packet_id: uuid.UUID) -> None:
    """Classify every page with Gemini Flash; persist EcvDocument rows.

    Idempotent: skips if EcvDocument rows already exist for this packet.
    Failure is logged and swallowed — downstream stages check for empty
    docs and handle gracefully.
    """
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(EcvDocument.id).where(EcvDocument.packet_id == packet_id).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            log.debug("classify: docs already exist for %s, skipping", packet_id)
            return

        packet_row = (
            await session.execute(
                select(Packet.org_id).where(Packet.id == packet_id)
            )
        ).scalar_one_or_none()
        if packet_row is None:
            log.warning("classify: packet %s vanished", packet_id)
            return
        org_id = packet_row

    try:
        classified = await classify_packet(packet_id)
    except Exception:
        log.exception("classify_packet failed for %s", packet_id)
        return

    if not classified:
        log.info("classify: no documents found for packet %s", packet_id)
        return

    doc_rows = [
        EcvDocument(
            packet_id=packet_id,
            org_id=org_id,
            doc_number=idx,
            name=doc["name"],
            mismo_type=doc["mismo_type"],
            pages_display=doc["pages_display"],
            page_count=doc["page_count"],
            confidence=doc["confidence"],
            status=doc["status"],
            category=doc["category"],
            page_issue_type=doc.get("page_issue_type"),
            page_issue_detail=doc.get("page_issue_detail"),
            page_issue_affected_page=doc.get("page_issue_affected_page"),
        )
        for idx, doc in enumerate(classified, start=1)
    ]

    async with SessionLocal() as session:
        session.add_all(doc_rows)
        await session.commit()

    log.info("classify: persisted %d document rows for packet %s", len(doc_rows), packet_id)


async def _run_extract(packet_id: uuid.UUID) -> None:
    """Extract MISMO 3.6 fields with Gemini Pro; persist EcvExtraction rows."""
    try:
        await extract_packet(packet_id)
    except Exception:
        log.exception("extract_packet failed for %s", packet_id)

    await confirm_program(packet_id)


async def _run_validate(packet_id: uuid.UUID) -> None:
    """Validate the 58-check ECV set with Claude; persist EcvSection/LineItem rows."""
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(EcvSection.id).where(EcvSection.packet_id == packet_id).limit(1)
            )
        ).scalar_one_or_none()
    if existing is not None:
        log.debug("validate: sections already exist for %s, skipping", packet_id)
        return

    try:
        await validate_packet(packet_id)
    except Exception:
        log.exception("validate_packet failed for %s", packet_id)


async def _run_score(packet_id: uuid.UUID) -> None:
    """Derive micro-app findings from the classified + extracted document text.

    All four derivation calls are concurrent; each is individually
    idempotent and failure-tolerant.
    """
    await asyncio.gather(
        derive_title_exam(packet_id),
        derive_income(packet_id),
        derive_compliance(packet_id),
        derive_title_search(packet_id),
    )
