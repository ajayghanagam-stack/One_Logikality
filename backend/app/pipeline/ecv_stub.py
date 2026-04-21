"""Deterministic ECV pipeline stub (US-3.4).

Fakes the multi-stage ECV pipeline so the upload → processing animation
can sync to real server state before the Temporal workflow lands.
Stages match `PIPELINE_STAGES` exactly — ingest / classify / extract /
validate / score / route — so the frontend `PipelineProgress` can port
the demo's labels/icons without translation.

Scheduled as a FastAPI `BackgroundTask` from `POST /api/packets`; runs
after the response is sent. Tests monkeypatch `STAGE_DELAY_SECONDS` to
something tiny so the polling loop terminates quickly without depending
on real time.

Background tasks don't carry the request's auth context, so writes go
through the default connection role (postgres superuser in local dev),
bypassing RLS intentionally — this is server-internal orchestration,
not a tenant-scoped request. The real ECV pipeline (Temporal workflow)
will run under a service identity that still enforces tenant isolation.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import EcvDocument, EcvLineItem, EcvSection, Packet
from app.pipeline.ecv_data import (
    CONFIRMATION_BY_PROGRAM,
    DOCUMENT_INVENTORY,
    ECV_LINE_ITEMS,
    ECV_SECTIONS,
)

log = logging.getLogger(__name__)

# Ordered, frozen — consumed by both the stub runner and the migration
# 0007 CHECK constraint. If this tuple changes, migration 0007 needs a
# follow-up to widen the allowed values.
PIPELINE_STAGES: tuple[str, ...] = (
    "ingest",
    "classify",
    "extract",
    "validate",
    "score",
    "route",
)

# Per-stage wall-clock delay. 0.8s gives the UI enough breathing room to
# highlight each stage icon without making the upload feel sluggish.
# Tests monkeypatch this to ~0.01s so polling terminates fast.
STAGE_DELAY_SECONDS: float = 0.8


async def run_ecv_stub(packet_id: uuid.UUID) -> None:
    """Walk a packet through the pipeline stages, updating its row after each.

    Flow: flip to `processing` + `started_processing_at`, then per stage
    write `current_stage=<stage>` and sleep, then flip to `completed` +
    `completed_at`. Any exception flips the packet to `failed` so the UI
    polling loop doesn't hang forever.
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
            if stage == "score":
                # Persist the canned findings as the `score` stage's
                # "output". Writes bypass RLS (no tenant context set on
                # SessionLocal) because this is internal orchestration —
                # the real workflow runs under a service identity that
                # still enforces tenant scoping.
                await _persist_findings(packet_id)
            # Module-attribute lookup so monkeypatching works without
            # callers having to re-import the value.
            await asyncio.sleep(STAGE_DELAY_SECONDS)

        async with SessionLocal() as session:
            await session.execute(
                update(Packet)
                .where(Packet.id == packet_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await session.commit()
    except Exception:
        log.exception("ECV stub failed for packet %s", packet_id)
        try:
            async with SessionLocal() as session:
                await session.execute(
                    update(Packet).where(Packet.id == packet_id).values(status="failed")
                )
                await session.commit()
        except Exception:
            log.exception("also failed to mark packet %s as failed", packet_id)


async def _persist_findings(packet_id: uuid.UUID) -> None:
    """Insert canned ECV sections / line items / documents for this packet.

    Re-running the stub against a packet that already has findings would
    trip the unique constraints on (packet_id, section_number) etc., so
    we short-circuit when rows already exist. That makes the stub safe
    to replay in dev after a hot reload.
    """
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(EcvSection.id).where(EcvSection.packet_id == packet_id).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        packet_row = (
            await session.execute(
                select(Packet.org_id, Packet.declared_program_id).where(Packet.id == packet_id)
            )
        ).one_or_none()
        if packet_row is None:
            log.warning("stub: packet %s vanished before findings write", packet_id)
            return
        org_id, declared_program_id = packet_row

        section_rows = [
            EcvSection(
                packet_id=packet_id,
                org_id=org_id,
                section_number=sec["id"],
                name=sec["name"],
                weight=sec["weight"],
                score=sec["score"],
            )
            for sec in ECV_SECTIONS
        ]
        session.add_all(section_rows)
        # Flush so section ids exist before we reference them on
        # line-item rows.
        await session.flush()

        section_by_number = {s.section_number: s for s in section_rows}
        line_item_rows: list[EcvLineItem] = []
        for section_number, items in ECV_LINE_ITEMS.items():
            parent = section_by_number[section_number]
            for item in items:
                line_item_rows.append(
                    EcvLineItem(
                        section_id=parent.id,
                        packet_id=packet_id,
                        org_id=org_id,
                        item_code=item["id"],
                        check_description=item["check"],
                        result_text=item["result"],
                        confidence=item["confidence"],
                    )
                )
        session.add_all(line_item_rows)

        doc_rows: list[EcvDocument] = []
        for doc in DOCUMENT_INVENTORY:
            issue = doc.get("page_issue")
            doc_rows.append(
                EcvDocument(
                    packet_id=packet_id,
                    org_id=org_id,
                    doc_number=doc["id"],
                    name=doc["name"],
                    mismo_type=doc["mismo_type"],
                    pages_display=doc["pages"],
                    page_count=doc["page_count"],
                    confidence=doc["confidence"],
                    status=doc["status"],
                    category=doc["category"],
                    page_issue_type=issue["type"] if issue else None,
                    page_issue_detail=issue["detail"] if issue else None,
                    page_issue_affected_page=issue["affected_page"] if issue else None,
                )
            )
        session.add_all(doc_rows)

        # Loan-program confirmation (US-3.11). Look up the canned verdict
        # for the declared program and stamp it onto the packet row.
        # Unknown program ids (shouldn't happen — the POST validates
        # against LOAN_PROGRAM_IDS) fall through to NULLs.
        confirmation = CONFIRMATION_BY_PROGRAM.get(declared_program_id)
        if confirmation is not None:
            await session.execute(
                update(Packet)
                .where(Packet.id == packet_id)
                .values(
                    program_confirmation_status=confirmation["status"],
                    program_confirmation_suggested_id=confirmation.get("suggested_program_id"),
                    program_confirmation_evidence=confirmation["evidence"],
                    program_confirmation_documents=list(confirmation["documents_analyzed"]),
                )
            )

        await session.commit()
