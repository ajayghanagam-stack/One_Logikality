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
from datetime import UTC, datetime
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
from app.deps import require_customer_admin, require_customer_role
from app.models import (
    APP_IDS,
    AppSubscription,
    EcvDocument,
    EcvLineItem,
    EcvSection,
    Packet,
    PacketFile,
    User,
)
from app.pipeline.ecv_stub import run_ecv_stub
from app.rules import APP_REQUIRED_DOCS, LOAN_PROGRAM_IDS

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


class ProgramConfirmationOut(BaseModel):
    """ECV document analysis for the declared program (US-3.11)."""

    status: str
    suggested_program_id: str | None
    evidence: str
    documents_analyzed: list[str]


class ProgramOverrideOut(BaseModel):
    """Packet-level program override audit record (US-3.12)."""

    program_id: str
    reason: str
    overridden_by: str
    overridden_by_name: str | None
    overridden_at: datetime


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
    # Loan-program confirmation + override (US-3.11 / US-3.12). Both
    # NULL until the pipeline has produced a verdict; override is NULL
    # until a customer admin changes the program away from declared.
    program_confirmation: ProgramConfirmationOut | None
    program_override: ProgramOverrideOut | None


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

    return _packet_out(packet, file_rows)


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


class MissingDocOut(BaseModel):
    """One missing MISMO doc type, with the reason it matters (US-5.1)."""

    mismo_type: str
    name: str
    reason: str


class AppGatingOut(BaseModel):
    """Per-app gating verdict surfaced by the ECV dashboard (US-5.2 / US-5.3).

    `status` is `ready` when every required MISMO doc type for the app
    appears as `status='found'` in the packet's document inventory, and
    `blocked` otherwise. `missing_docs` is always emitted as a list so
    the frontend can render "BLOCKED · N missing" without a null check;
    `ready` apps get an empty list.

    Only apps the org is subscribed to AND has enabled appear in the
    payload — disabled/unsubscribed apps aren't gating candidates.
    """

    app_id: str
    status: str
    missing_docs: list[MissingDocOut]


class EcvDashboardOut(BaseModel):
    packet: PacketOut
    summary: EcvSummaryOut
    sections: list[EcvSectionOut]
    documents: list[EcvDocumentOut]
    app_gating: list[AppGatingOut]


# Severity thresholds are surfaced alongside the data so the frontend
# can keep a single source of truth without hardcoding the same numbers
# in TypeScript.
_CONFIDENCE_THRESHOLD = 85
_CRITICAL_THRESHOLD = 50
_AUTO_APPROVE_THRESHOLD = 90

# Override reason must be long enough to be a real audit-trail note, not
# "ok". Matches the demo's 5-char floor so users aren't surprised by a
# stricter rule after the port.
_MIN_OVERRIDE_REASON_LENGTH = 5


def _packet_out(
    packet: Packet,
    files: list[PacketFile],
    overrider_name: str | None = None,
) -> PacketOut:
    """Serialize a Packet (+ files) into the wire shape.

    Folds in the confirmation and override sub-objects so every packet
    response shares one source of truth. `overrider_name` is looked up
    separately by the caller (it's on `users`, not on `packets`) and
    passed in for inclusion on the override block; NULL when the packet
    has no override or when the overriding user has since been deleted.
    """
    confirmation: ProgramConfirmationOut | None = None
    if packet.program_confirmation_status is not None:
        confirmation = ProgramConfirmationOut(
            status=packet.program_confirmation_status,
            suggested_program_id=packet.program_confirmation_suggested_id,
            evidence=packet.program_confirmation_evidence or "",
            documents_analyzed=list(packet.program_confirmation_documents or []),
        )

    override: ProgramOverrideOut | None = None
    if (
        packet.program_overridden_to is not None
        and packet.program_override_reason is not None
        and packet.program_overridden_by is not None
        and packet.program_overridden_at is not None
    ):
        override = ProgramOverrideOut(
            program_id=packet.program_overridden_to,
            reason=packet.program_override_reason,
            overridden_by=str(packet.program_overridden_by),
            overridden_by_name=overrider_name,
            overridden_at=packet.program_overridden_at,
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
        program_confirmation=confirmation,
        program_override=override,
    )


async def _fetch_overrider_name(session: AsyncSession, packet: Packet) -> str | None:
    """Look up the overrider's full_name when the packet has an override.

    Returns None if the user row has been deleted (FK is SET NULL, so
    `program_overridden_by` can also be NULL while the timestamp is not
    — in that case the client shows "by unknown user").
    """
    if packet.program_overridden_by is None:
        return None
    return (
        await session.execute(select(User.full_name).where(User.id == packet.program_overridden_by))
    ).scalar_one_or_none()


class ProgramOverrideIn(BaseModel):
    """Body for `POST /api/packets/{id}/program-override`."""

    program_id: str
    reason: str


@router.post("/{packet_id}/program-override", response_model=PacketOut)
async def set_packet_program_override(
    packet_id: uuid.UUID,
    body: ProgramOverrideIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_admin)],
) -> PacketOut:
    """Override the declared loan program for this packet (US-3.12).

    Restricted to customer admins — changing the program swaps the
    entire rule baseline and is a customer-admin-level decision. A
    replay of the same program is treated as a no-op; changing to the
    declared program with a reason is allowed (records intent). The
    reason is required (>= 5 chars) and stored in the audit trail.
    """
    if body.program_id not in LOAN_PROGRAM_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown program id {body.program_id!r}",
        )
    reason = body.reason.strip()
    if len(reason) < _MIN_OVERRIDE_REASON_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"reason must be at least {_MIN_OVERRIDE_REASON_LENGTH} characters",
        )

    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    packet.program_overridden_to = body.program_id
    packet.program_override_reason = reason
    packet.program_overridden_by = user.id
    packet.program_overridden_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(packet)

    files = (
        (await session.execute(select(PacketFile).where(PacketFile.packet_id == packet_id)))
        .scalars()
        .all()
    )
    overrider_name = user.full_name  # we know who it is — the current user
    return _packet_out(packet, list(files), overrider_name=overrider_name)


@router.delete("/{packet_id}/program-override", response_model=PacketOut)
async def clear_packet_program_override(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_admin)],
) -> PacketOut:
    """Revert a packet-level program override back to the declared program.

    Idempotent — reverting a packet that has no override returns the
    current packet unchanged.
    """
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    packet.program_overridden_to = None
    packet.program_override_reason = None
    packet.program_overridden_by = None
    packet.program_overridden_at = None
    await session.commit()
    await session.refresh(packet)

    files = (
        (await session.execute(select(PacketFile).where(PacketFile.packet_id == packet_id)))
        .scalars()
        .all()
    )
    return _packet_out(packet, list(files), overrider_name=None)


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
    overrider_name = await _fetch_overrider_name(session, packet)
    return _packet_out(packet, list(files), overrider_name=overrider_name)


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
    overrider_name = await _fetch_overrider_name(session, packet)
    packet_out = _packet_out(packet, list(files), overrider_name=overrider_name)

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

    app_gating = await _compute_app_gating(session, packet.org_id, documents)

    return EcvDashboardOut(
        packet=packet_out,
        summary=summary,
        sections=section_outs,
        documents=document_outs,
        app_gating=app_gating,
    )


async def _compute_app_gating(
    session: AsyncSession,
    org_id: uuid.UUID,
    documents: list[EcvDocument],
) -> list[AppGatingOut]:
    """Gating verdict per subscribed+enabled app (US-5.2 / US-5.3).

    Apps the org isn't subscribed to — or has disabled — are omitted
    entirely so the dashboard launcher only shows what the user could
    actually open. ECV has no manifest and never gates itself.

    The found/missing split is derived from the packet's `ecv_documents`
    inventory: a required MISMO type is satisfied only if at least one
    document of that type is `status='found'`. Missing docs are emitted
    in manifest order with the demo's friendly names + reasons so the
    blocked-app dialog reads the same on both products.
    """
    # Preserve APP_IDS order so the launcher renders deterministically —
    # ECV first, then the paid apps in catalog order.
    subs = (
        (await session.execute(select(AppSubscription).where(AppSubscription.org_id == org_id)))
        .scalars()
        .all()
    )
    enabled_ids = {s.app_id for s in subs if s.enabled}

    found_mismo_types = {d.mismo_type for d in documents if d.status == "found"}

    gating: list[AppGatingOut] = []
    for app_id in APP_IDS:
        if app_id not in enabled_ids:
            continue
        manifest = APP_REQUIRED_DOCS.get(app_id, ())
        missing = [
            MissingDocOut(
                mismo_type=doc["mismo_type"],
                name=_doc_name_from_mismo(doc["mismo_type"]),
                reason=doc["reason"],
            )
            for doc in manifest
            if doc["mismo_type"] not in found_mismo_types
        ]
        gating.append(
            AppGatingOut(
                app_id=app_id,
                status="blocked" if missing else "ready",
                missing_docs=missing,
            )
        )
    return gating


# Pretty display name per MISMO type — mirrors the demo's friendly labels
# on the blocked-app dialog. Unknown types fall back to the raw MISMO
# string so new additions aren't invisible.
_MISMO_DISPLAY_NAMES: dict[str, str] = {
    "TITLE_COMMITMENT": "Title Commitment",
    "WARRANTY_DEED": "Warranty Deed",
    "DEED_OF_TRUST": "Deed of Trust",
    "TAX_CERTIFICATE": "Tax Certificate",
    "LOAN_ESTIMATE": "Loan Estimate",
    "CLOSING_DISCLOSURE": "Closing Disclosure",
    "LEAD_PAINT_DISCLOSURE": "Lead Paint Disclosure",
    "STATE_DISCLOSURE": "State-specific Disclosure",
    "AFFILIATED_BUSINESS": "Affiliated Business Disclosure",
    "URLA_1003": "URLA (Form 1003)",
    "W2_WAGE_STATEMENT": "W-2 Wage Statement",
    "PAYSTUB": "Paystub",
    "TAX_RETURN_1040": "1040 Tax Return",
    "TAX_SCHEDULE_E": "Schedule E",
    "VOE": "Verification of Employment",
}


def _doc_name_from_mismo(mismo_type: str) -> str:
    return _MISMO_DISPLAY_NAMES.get(mismo_type, mismo_type)
