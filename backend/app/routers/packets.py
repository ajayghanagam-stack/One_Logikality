"""Packet upload API (US-3.1 / US-3.2 / US-3.3).

`POST /api/packets` — multipart/form-data: one or more `files` plus the
declared loan program. Every authenticated customer role (admin and
user) can upload; reads are org-scoped via RLS. The declared program is
persisted on the row so rule resolution at processing time stays
reproducible even if org config changes mid-flight.

The deterministic ECV stub (US-3.4) runs as a FastAPI BackgroundTask
after the response is sent; it flips the packet through `processing`
→ `completed` one stage at a time so the upload → pipeline-animation
hand-off can sync to real server state. The real Temporal workflow
replaces the stub in a later slice.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage_local import get_storage
from app.db import get_session
from app.deps import require_customer_role
from app.models import EcvDocument, EcvLineItem, EcvSection, Packet, PacketFile, User
from app.pipeline.ecv_stub import run_ecv_stub
from app.rules import LOAN_PROGRAM_IDS

router = APIRouter(prefix="/api/packets", tags=["packets"])

# 100 MB per file. Arbitrary but generous for mortgage packets; a 2,000-
# page scanned PDF at typical density is well under that. Revisit when
# we have real ingest traffic.
_MAX_FILE_BYTES = 100 * 1024 * 1024

# Accept the extensions the demo's upload page advertises. Content-type
# is unreliable for PDFs coming through different browsers, so we filter
# on file extension and trust the byte stream behind it.
_ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


class PacketFileOut(BaseModel):
    id: str
    filename: str
    size_bytes: int
    content_type: str


class PacketOut(BaseModel):
    id: str
    declared_program_id: str
    status: str
    # Pipeline-state triple (US-3.4). `current_stage` is one of the ids
    # in `PIPELINE_STAGES`; all three are NULL until the stub begins
    # running, and `completed_at` is only set once `status == 'completed'`.
    current_stage: str | None
    started_processing_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    files: list[PacketFileOut]


def _extension(filename: str) -> str:
    # Lowercase last segment after the final dot. Guards against "UPPER.PDF".
    _, _, ext = filename.rpartition(".")
    return f".{ext.lower()}" if ext else ""


@router.post("", response_model=PacketOut, status_code=status.HTTP_201_CREATED)
async def create_packet(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
    background: BackgroundTasks,
    declared_program_id: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
) -> PacketOut:
    if declared_program_id not in LOAN_PROGRAM_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown program id {declared_program_id!r}",
        )
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="at least one file is required",
        )

    # Read everything before we touch the DB — if any file is oversized
    # or has a disallowed extension we reject cleanly with 400 and don't
    # leave a half-built packet around.
    buffered: list[tuple[UploadFile, bytes]] = []
    for upload in files:
        name = upload.filename or ""
        if _extension(name) not in _ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unsupported file type: {name!r}",
            )
        data = await upload.read()
        if len(data) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"empty file: {name!r}",
            )
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"file too large: {name!r}",
            )
        buffered.append((upload, data))

    # RLS guarantees org_id would be own-org anyway, but we set it
    # explicitly so the row is valid even when tests bypass RLS by
    # connecting as the postgres superuser.
    assert user.org_id is not None  # customer roles always carry an org
    packet = Packet(
        org_id=user.org_id,
        declared_program_id=declared_program_id,
        status="uploaded",
        created_by=user.id,
    )
    session.add(packet)
    await session.flush()  # populate packet.id before child rows reference it

    storage = get_storage()
    file_rows: list[PacketFile] = []
    for upload, data in buffered:
        file_id = uuid.uuid4()
        # Namespaced under org/packet so a single storage root can serve
        # every tenant without leaking keys; the file_id prefix makes
        # collisions from repeated filenames impossible.
        safe_name = (upload.filename or "file").replace("/", "_")
        key = f"packets/{packet.org_id}/{packet.id}/{file_id}__{safe_name}"
        await storage.put(key, data)

        file_rows.append(
            PacketFile(
                id=file_id,
                packet_id=packet.id,
                org_id=packet.org_id,
                filename=safe_name,
                size_bytes=len(data),
                content_type=upload.content_type or "application/octet-stream",
                storage_key=key,
            )
        )
    session.add_all(file_rows)
    await session.commit()
    await session.refresh(packet)

    # Kick off the deterministic ECV stub. BackgroundTasks runs after the
    # response has been sent, so the client can start polling /api/packets/{id}
    # immediately and watch `current_stage` tick through PIPELINE_STAGES.
    background.add_task(run_ecv_stub, packet.id)

    return PacketOut(
        id=str(packet.id),
        declared_program_id=packet.declared_program_id,
        status=packet.status,
        current_stage=packet.current_stage,
        started_processing_at=packet.started_processing_at,
        completed_at=packet.completed_at,
        created_at=packet.created_at,
        files=[
            PacketFileOut(
                id=str(f.id),
                filename=f.filename,
                size_bytes=f.size_bytes,
                content_type=f.content_type,
            )
            for f in file_rows
        ],
    )


class EcvLineItemOut(BaseModel):
    id: str
    item_code: str
    check: str
    result: str
    confidence: int


class EcvSectionOut(BaseModel):
    id: str
    section_number: int
    name: str
    weight: int
    score: float
    line_items: list[EcvLineItemOut]


class EcvPageIssueOut(BaseModel):
    type: str
    detail: str
    affected_page: int


class EcvDocumentOut(BaseModel):
    id: str
    doc_number: int
    name: str
    mismo_type: str
    pages: str
    page_count: int
    confidence: int
    status: str
    category: str
    page_issue: EcvPageIssueOut | None


class EcvSummaryOut(BaseModel):
    """Top-line counts the dashboard hero / KPIs render without recomputing."""

    overall_score: float
    auto_approve_threshold: int
    confidence_threshold: int
    critical_threshold: int
    total_items: int
    passed_items: int
    review_items: int
    critical_items: int
    documents_found: int
    documents_missing: int


class EcvDashboardOut(BaseModel):
    packet: PacketOut
    summary: EcvSummaryOut
    sections: list[EcvSectionOut]
    documents: list[EcvDocumentOut]


# Severity thresholds are surfaced alongside the data so the frontend
# can keep a single source of truth without hardcoding the same numbers
# in TypeScript.
_CONFIDENCE_THRESHOLD = 85
_CRITICAL_THRESHOLD = 50
_AUTO_APPROVE_THRESHOLD = 90


@router.get("/{packet_id}", response_model=PacketOut)
async def get_packet(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> PacketOut:
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        # Could be "not yours" (RLS filtered it) or "doesn't exist" — we
        # return 404 in both cases so the API doesn't leak existence
        # across tenants.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    files = (
        (await session.execute(select(PacketFile).where(PacketFile.packet_id == packet_id)))
        .scalars()
        .all()
    )
    return PacketOut(
        id=str(packet.id),
        declared_program_id=packet.declared_program_id,
        status=packet.status,
        current_stage=packet.current_stage,
        started_processing_at=packet.started_processing_at,
        completed_at=packet.completed_at,
        created_at=packet.created_at,
        files=[
            PacketFileOut(
                id=str(f.id),
                filename=f.filename,
                size_bytes=f.size_bytes,
                content_type=f.content_type,
            )
            for f in files
        ],
    )


@router.get("/{packet_id}/ecv", response_model=EcvDashboardOut)
async def get_packet_ecv(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> EcvDashboardOut:
    """Return the ECV dashboard payload for a packet.

    Everything the dashboard needs to render — packet header, overall
    weighted score + severity counts, the 13 sections with their line
    items, and the MISMO document inventory — in a single round trip.
    RLS scopes every query, so a 404 covers both "doesn't exist" and
    "not yours" without leaking existence across tenants.
    """
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    files = (
        (await session.execute(select(PacketFile).where(PacketFile.packet_id == packet_id)))
        .scalars()
        .all()
    )
    packet_out = PacketOut(
        id=str(packet.id),
        declared_program_id=packet.declared_program_id,
        status=packet.status,
        current_stage=packet.current_stage,
        started_processing_at=packet.started_processing_at,
        completed_at=packet.completed_at,
        created_at=packet.created_at,
        files=[
            PacketFileOut(
                id=str(f.id),
                filename=f.filename,
                size_bytes=f.size_bytes,
                content_type=f.content_type,
            )
            for f in files
        ],
    )

    # Findings aren't persisted until the stub reaches the `score`
    # stage. Before that, tell the client so it can show a "still
    # processing" state instead of a zero-filled dashboard.
    sections = (
        (
            await session.execute(
                select(EcvSection)
                .where(EcvSection.packet_id == packet_id)
                .order_by(EcvSection.section_number)
            )
        )
        .scalars()
        .all()
    )
    if not sections:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ECV findings not ready yet",
        )

    line_items = (
        (
            await session.execute(
                select(EcvLineItem)
                .where(EcvLineItem.packet_id == packet_id)
                .order_by(EcvLineItem.item_code)
            )
        )
        .scalars()
        .all()
    )
    documents = (
        (
            await session.execute(
                select(EcvDocument)
                .where(EcvDocument.packet_id == packet_id)
                .order_by(EcvDocument.doc_number)
            )
        )
        .scalars()
        .all()
    )

    items_by_section: dict[uuid.UUID, list[EcvLineItem]] = {}
    for item in line_items:
        items_by_section.setdefault(item.section_id, []).append(item)

    section_outs: list[EcvSectionOut] = []
    for sec in sections:
        section_outs.append(
            EcvSectionOut(
                id=str(sec.id),
                section_number=sec.section_number,
                name=sec.name,
                weight=sec.weight,
                score=float(sec.score),
                line_items=[
                    EcvLineItemOut(
                        id=str(i.id),
                        item_code=i.item_code,
                        check=i.check_description,
                        result=i.result_text,
                        confidence=i.confidence,
                    )
                    for i in items_by_section.get(sec.id, [])
                ],
            )
        )

    document_outs = [
        EcvDocumentOut(
            id=str(d.id),
            doc_number=d.doc_number,
            name=d.name,
            mismo_type=d.mismo_type,
            pages=d.pages_display,
            page_count=d.page_count,
            confidence=d.confidence,
            status=d.status,
            category=d.category,
            page_issue=(
                EcvPageIssueOut(
                    type=d.page_issue_type,
                    detail=d.page_issue_detail or "",
                    affected_page=d.page_issue_affected_page or 0,
                )
                if d.page_issue_type is not None
                else None
            ),
        )
        for d in documents
    ]

    # Weighted overall score — mirrors demo's rollup. Sections with
    # weight 0 don't contribute; divide-by-zero is impossible unless the
    # seed data is broken.
    total_weight = sum(s.weight for s in sections)
    overall_score = (
        sum(float(s.score) * s.weight for s in sections) / total_weight if total_weight > 0 else 0.0
    )

    critical = [i for i in line_items if i.confidence < _CRITICAL_THRESHOLD]
    review = [i for i in line_items if _CRITICAL_THRESHOLD <= i.confidence < _CONFIDENCE_THRESHOLD]
    passed = [i for i in line_items if i.confidence >= _CONFIDENCE_THRESHOLD]
    missing_docs = sum(1 for d in documents if d.status == "missing")

    summary = EcvSummaryOut(
        overall_score=round(overall_score, 1),
        auto_approve_threshold=_AUTO_APPROVE_THRESHOLD,
        confidence_threshold=_CONFIDENCE_THRESHOLD,
        critical_threshold=_CRITICAL_THRESHOLD,
        total_items=len(line_items),
        passed_items=len(passed),
        review_items=len(review),
        critical_items=len(critical),
        documents_found=len(documents) - missing_docs,
        documents_missing=missing_docs,
    )

    return EcvDashboardOut(
        packet=packet_out,
        summary=summary,
        sections=section_outs,
        documents=document_outs,
    )
