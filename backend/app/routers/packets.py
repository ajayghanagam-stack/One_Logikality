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

import hashlib
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
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage_local import get_storage
from app.db import get_session
from app.deps import require_customer_admin, require_customer_role
from app.exports import render_ecv_mismo_xml, render_ecv_pdf
from app.models import (
    APP_IDS,
    REVIEW_STATES,
    AppSubscription,
    ComplianceCheck,
    ComplianceFinding,
    ComplianceFeeTolerance,
    CompliancePacketMetadata,
    EcvDocument,
    EcvExtraction,
    EcvLineItem,
    EcvSection,
    IncomeDtiItem,
    IncomeFinding,
    IncomePacketMetadata,
    IncomeSource,
    Packet,
    PacketFile,
    TitleExamChecklistItem,
    TitleExamException,
    TitleExamRequirement,
    TitleExamWarning,
    TitleFlag,
    TitleProperty,
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


class PacketReviewOut(BaseModel):
    """Packet review decision surfaced in the ECV action bar (US-8.3)."""

    state: str
    notes: str | None
    transitioned_by: str | None
    transitioned_by_name: str | None
    transitioned_at: datetime


class PacketOut(BaseModel):
    id: str
    declared_program_id: str
    # Which micro-apps this packet was uploaded to be scored against.
    # ECV is always included. Drives the ECV dashboard's coverage card
    # and the out-of-scope collapse behavior.
    scoped_app_ids: list[str]
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
    # Review state (US-8.3). NULL until the customer records a decision.
    review: PacketReviewOut | None


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
    # Comma-separated list of app ids this packet should be scored against.
    # Optional: if omitted (older clients), we fall back to `ecv` only so
    # the dashboard never shows out-of-scope red by default. The upload UI
    # always sends an explicit list.
    scoped_app_ids: Annotated[str | None, Form()] = None,
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
    scope_list = _parse_scope(scoped_app_ids)

    # Read everything before we touch the DB — if any file is oversized
    # or has a disallowed extension we reject cleanly with 400 and don't
    # leave a half-built packet around. We also hash each file up front
    # so the dedupe lookup below can compare sets of SHA256 digests.
    buffered: list[tuple[UploadFile, bytes, str]] = []
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
        buffered.append((upload, data, hashlib.sha256(data).hexdigest()))

    # RLS guarantees org_id would be own-org anyway, but we set it
    # explicitly so the row is valid even when tests bypass RLS by
    # connecting as the postgres superuser.
    assert user.org_id is not None  # customer roles always carry an org

    # Deterministic-dedupe: the real ECV pipeline calls Gemini / Claude,
    # which drift across runs even at temperature=0. If the same user
    # re-uploads an identical file set under the same program, return the
    # existing completed packet so the dashboard stays stable and we
    # don't burn tokens re-running classify / extract / validate.
    incoming_hashes = sorted(h for _, _, h in buffered)
    duplicate = await _find_duplicate_packet(
        session,
        declared_program_id=declared_program_id,
        file_hashes=incoming_hashes,
        scoped_app_ids=scope_list,
    )
    if duplicate is not None:
        dup_files = (
            (await session.execute(select(PacketFile).where(PacketFile.packet_id == duplicate.id)))
            .scalars()
            .all()
        )
        overrider_name = await _fetch_overrider_name(session, duplicate)
        reviewer_name = await _fetch_reviewer_name(session, duplicate)
        return _packet_out(
            duplicate,
            list(dup_files),
            overrider_name=overrider_name,
            reviewer_name=reviewer_name,
        )

    packet = Packet(
        org_id=user.org_id,
        declared_program_id=declared_program_id,
        status="uploaded",
        created_by=user.id,
        scoped_app_ids=scope_list,
    )
    session.add(packet)
    await session.flush()  # populate packet.id before child rows reference it

    storage = get_storage()
    file_rows: list[PacketFile] = []
    for upload, data, content_hash in buffered:
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
                content_hash=content_hash,
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


def _parse_scope(raw: str | None) -> list[str]:
    """Parse the upload form's comma-separated scope into a validated list.

    Rules:
      - None / empty → ["ecv"] (safe default: only the foundational app).
      - "ecv" is always forced in; callers can't opt out of it.
      - Unknown ids are rejected with 400 so typos don't silently widen
        or narrow scope.
      - Order-independent and deduplicated.
    """
    if not raw or not raw.strip():
        return ["ecv"]
    parsed = [part.strip() for part in raw.split(",") if part.strip()]
    for app_id in parsed:
        if app_id not in APP_IDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown app id in scoped_app_ids: {app_id!r}",
            )
    scope_set = set(parsed)
    scope_set.add("ecv")  # always in scope
    return sorted(scope_set)


async def _find_duplicate_packet(
    session: AsyncSession,
    *,
    declared_program_id: str,
    file_hashes: list[str],
    scoped_app_ids: list[str],
) -> Packet | None:
    """Return a completed packet whose files match `file_hashes` exactly.

    Scope is the caller's own org (enforced by RLS on the SELECT, which
    runs under the request's tenant session), same `declared_program_id`
    (different program = different rule baseline = legitimately
    different run), AND same `scoped_app_ids` — changing scope means a
    different set of checks count toward the score, so re-using a cached
    packet from a different scope would misrepresent the outcome.

    `file_hashes` is the sorted list of SHA256 digests on the incoming
    upload. A match means "same multiset of file bytes", regardless of
    order or original filenames.
    """
    if not file_hashes:
        return None

    # Candidate packets: completed, same program, owned by the caller's
    # org (RLS), and with the same number of files as the incoming set.
    # We narrow with a subquery on PacketFile so we don't scan every
    # packet the org has uploaded.
    candidate_rows = (
        await session.execute(
            select(Packet, PacketFile.content_hash)
            .join(PacketFile, PacketFile.packet_id == Packet.id)
            .where(
                Packet.declared_program_id == declared_program_id,
                Packet.status == "completed",
                PacketFile.content_hash.in_(file_hashes),
            )
        )
    ).all()
    if not candidate_rows:
        return None

    # Group digests by packet so we can compare multisets.
    hashes_by_packet: dict[uuid.UUID, list[str]] = {}
    packet_by_id: dict[uuid.UUID, Packet] = {}
    for packet, digest in candidate_rows:
        hashes_by_packet.setdefault(packet.id, []).append(digest)
        packet_by_id[packet.id] = packet

    for packet_id in hashes_by_packet:
        # A partial match on the join isn't enough — a candidate with
        # extra files is a different upload. Re-query the full file set
        # to be sure we compare the complete multiset, not just the
        # overlapping hashes.
        full_hashes = (
            (
                await session.execute(
                    select(PacketFile.content_hash).where(PacketFile.packet_id == packet_id)
                )
            )
            .scalars()
            .all()
        )
        if sorted(full_hashes) != file_hashes:
            continue
        candidate = packet_by_id[packet_id]
        if sorted(candidate.scoped_app_ids or []) != sorted(scoped_app_ids):
            continue
        return candidate
    return None


class ScopeOptionRow(BaseModel):
    """One selectable app on the upload page's scope picker.

    `subscribed` / `enabled` mirror the customer-admin /apps shape so the
    upload form can reuse the same mental model. `enabled=false` options
    are rendered disabled with a "Ask your admin to enable" hint.
    """

    app_id: str
    subscribed: bool
    enabled: bool


@router.get("/scope-options", response_model=list[ScopeOptionRow])
async def list_scope_options(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> list[ScopeOptionRow]:
    """Which micro-apps the current org can scope a packet to.

    Every customer role can read this (it's needed on the upload form,
    which customer_user also has access to). Returns one row per known
    app id in catalog order so the frontend never has to reconcile
    missing rows.
    """
    subs = {
        row.app_id: row
        for row in (
            await session.execute(
                select(AppSubscription).where(AppSubscription.org_id == user.org_id)
            )
        )
        .scalars()
        .all()
    }
    return [
        ScopeOptionRow(
            app_id=app_id,
            subscribed=app_id in subs,
            enabled=subs[app_id].enabled if app_id in subs else False,
        )
        for app_id in APP_IDS
    ]


@router.get("", response_model=list[PacketOut])
async def list_packets(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> list[PacketOut]:
    """List packets for the current user's org, most-recent first.

    RLS scopes the SELECT to the caller's org. Files + overrider/reviewer
    names are bulk-loaded in two follow-up queries to avoid N+1.
    """
    packets = (
        (await session.execute(select(Packet).order_by(Packet.created_at.desc()))).scalars().all()
    )
    if not packets:
        return []

    packet_ids = [p.id for p in packets]
    file_rows = (
        (await session.execute(select(PacketFile).where(PacketFile.packet_id.in_(packet_ids))))
        .scalars()
        .all()
    )
    files_by_packet: dict[uuid.UUID, list[PacketFile]] = {pid: [] for pid in packet_ids}
    for f in file_rows:
        files_by_packet[f.packet_id].append(f)

    user_ids: set[uuid.UUID] = set()
    for p in packets:
        if p.program_overridden_by is not None:
            user_ids.add(p.program_overridden_by)
        if p.review_by_user_id is not None:
            user_ids.add(p.review_by_user_id)
    names_by_user: dict[uuid.UUID, str] = {}
    if user_ids:
        name_rows = (
            await session.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
        ).all()
        names_by_user = {uid: name for uid, name in name_rows}

    return [
        _packet_out(
            p,
            files_by_packet.get(p.id, []),
            overrider_name=(
                names_by_user.get(p.program_overridden_by)
                if p.program_overridden_by is not None
                else None
            ),
            reviewer_name=(
                names_by_user.get(p.review_by_user_id) if p.review_by_user_id is not None else None
            ),
        )
        for p in packets
    ]


class EcvLineItemOut(BaseModel):
    id: str
    item_code: str
    check: str
    result: str
    confidence: int
    # Downstream apps this check feeds. NULL/empty means "core ECV check".
    # Surfaced so the UI can label scope on hover / drill-down.
    app_ids: list[str]
    # Resolved against the packet's scope. Out-of-scope items are still
    # returned (for audit / "what would change if I added this app?") but
    # don't contribute to the section score or severity counts.
    in_scope: bool


class EcvSectionOut(BaseModel):
    id: str
    section_number: int
    name: str
    weight: int
    # Score now computed from the in-scope line items only; this is the
    # number displayed in the UI. `raw_score` preserves the original
    # rollup (all items) for audit / debugging.
    score: float
    raw_score: float
    # A section is in-scope when it has at least one in-scope line item.
    # Sections with zero in-scope items are rendered as "Not scored —
    # out of scope for this packet" and do not contribute to overall_score.
    in_scope: bool
    # drives_score is True when this section contributes to the overall_score
    # gauge. When non-ECV apps are selected, only sections with items
    # explicitly tagged for those apps drive the score — core ECV sections
    # (empty app_ids) are visible but don't pull the headline number.
    drives_score: bool
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


class AppCoverageOut(BaseModel):
    """Per-app scoring coverage for this packet (in-scope apps only).

    Computed from line items tagged with this app. `total_items` / `passed`
    / `review` / `critical` are the same severity buckets used by the
    global summary but scoped to one app so the Coverage card can render
    "Title Exam — 8/8 in scope, 82% score" at a glance.
    """

    app_id: str
    total_items: int
    passed_items: int
    review_items: int
    critical_items: int
    score: float


class EcvDashboardOut(BaseModel):
    packet: PacketOut
    summary: EcvSummaryOut
    sections: list[EcvSectionOut]
    documents: list[EcvDocumentOut]
    app_gating: list[AppGatingOut]
    # One row per app the packet is scoped to (always includes ECV).
    # Empty if no line items exist yet (pre-score pipeline stages).
    coverage: list[AppCoverageOut]


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
    reviewer_name: str | None = None,
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

    review: PacketReviewOut | None = None
    if packet.review_state is not None and packet.review_transitioned_at is not None:
        review = PacketReviewOut(
            state=packet.review_state,
            notes=packet.review_notes,
            transitioned_by=(
                str(packet.review_by_user_id) if packet.review_by_user_id is not None else None
            ),
            transitioned_by_name=reviewer_name,
            transitioned_at=packet.review_transitioned_at,
        )

    return PacketOut(
        id=str(packet.id),
        declared_program_id=packet.declared_program_id,
        scoped_app_ids=list(packet.scoped_app_ids or ["ecv"]),
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
        review=review,
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


async def _fetch_reviewer_name(session: AsyncSession, packet: Packet) -> str | None:
    """Look up the reviewer's full_name for the current review-state row.

    Mirrors `_fetch_overrider_name` — returns None when the user row has
    been deleted so the UI renders "by unknown user" without joining.
    """
    if packet.review_by_user_id is None:
        return None
    return (
        await session.execute(select(User.full_name).where(User.id == packet.review_by_user_id))
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
    reviewer_name = await _fetch_reviewer_name(session, packet)
    return _packet_out(
        packet,
        list(files),
        overrider_name=overrider_name,
        reviewer_name=reviewer_name,
    )


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
    reviewer_name = await _fetch_reviewer_name(session, packet)
    return _packet_out(
        packet,
        list(files),
        overrider_name=None,
        reviewer_name=reviewer_name,
    )


@router.post("/{packet_id}/reprocess", response_model=PacketOut)
async def reprocess_packet(
    packet_id: uuid.UUID,
    background: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_admin)],
) -> PacketOut:
    """Reset a completed packet and re-run the ECV pipeline from scratch.

    Clears all derived ECV data (sections, line items, documents,
    extractions) and resets the packet back to `pending` so the pipeline
    stub can run again — useful after a loan-program override changes
    which rule-set applies to the packet.
    """
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    # Clear all derived pipeline data so the stub can write fresh rows.
    # EcvSection cascade-deletes EcvLineItem; EcvDocument cascade-deletes
    # nothing, so we delete it explicitly. Compliance / Income / Title
    # tables all have unique constraints on (packet_id, …) so they must
    # also be cleared before the stub can re-insert them.
    await session.execute(delete(EcvSection).where(EcvSection.packet_id == packet_id))
    await session.execute(delete(EcvDocument).where(EcvDocument.packet_id == packet_id))
    await session.execute(delete(EcvExtraction).where(EcvExtraction.packet_id == packet_id))
    await session.execute(delete(ComplianceCheck).where(ComplianceCheck.packet_id == packet_id))
    await session.execute(delete(ComplianceFinding).where(ComplianceFinding.packet_id == packet_id))
    await session.execute(delete(ComplianceFeeTolerance).where(ComplianceFeeTolerance.packet_id == packet_id))
    await session.execute(delete(CompliancePacketMetadata).where(CompliancePacketMetadata.packet_id == packet_id))
    await session.execute(delete(IncomeSource).where(IncomeSource.packet_id == packet_id))
    await session.execute(delete(IncomeDtiItem).where(IncomeDtiItem.packet_id == packet_id))
    await session.execute(delete(IncomeFinding).where(IncomeFinding.packet_id == packet_id))
    await session.execute(delete(IncomePacketMetadata).where(IncomePacketMetadata.packet_id == packet_id))
    await session.execute(delete(TitleFlag).where(TitleFlag.packet_id == packet_id))
    await session.execute(delete(TitleProperty).where(TitleProperty.packet_id == packet_id))
    await session.execute(delete(TitleExamException).where(TitleExamException.packet_id == packet_id))
    await session.execute(delete(TitleExamRequirement).where(TitleExamRequirement.packet_id == packet_id))
    await session.execute(delete(TitleExamWarning).where(TitleExamWarning.packet_id == packet_id))
    await session.execute(delete(TitleExamChecklistItem).where(TitleExamChecklistItem.packet_id == packet_id))

    # Reset packet to uploaded so the stub can walk through its stages again.
    packet.status = "uploaded"
    packet.current_stage = None
    packet.started_processing_at = None
    packet.completed_at = None

    await session.commit()
    await session.refresh(packet)

    background.add_task(run_ecv_stub, packet_id)

    files = (
        (await session.execute(select(PacketFile).where(PacketFile.packet_id == packet_id)))
        .scalars()
        .all()
    )
    overrider_name = await _fetch_overrider_name(session, packet)
    reviewer_name = await _fetch_reviewer_name(session, packet)
    return _packet_out(
        packet,
        list(files),
        overrider_name=overrider_name,
        reviewer_name=reviewer_name,
    )


class PacketReviewIn(BaseModel):
    """Body for `POST /api/packets/{id}/review` (US-8.3).

    `state` is the target review state (`pending_manual_review` /
    `approved` / `rejected`). `notes` is the rationale the underwriter
    enters in the dialog; required for `rejected` (auditable reason for
    a negative decision) and optional for the other two.
    """

    state: str
    notes: str | None = None


_MIN_REVIEW_NOTES_LENGTH = 5


@router.post("/{packet_id}/review", response_model=PacketOut)
async def set_packet_review(
    packet_id: uuid.UUID,
    body: PacketReviewIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> PacketOut:
    """Record a review decision on the packet (US-8.3).

    Any authenticated customer role can set the state — approve / reject
    are the authoritative decisions, and "send to manual review" just
    flags the packet for a second pair of eyes. Every transition
    refreshes `review_transitioned_at` and replaces `review_by_user_id`,
    so the audit trail always reflects the most recent actor.
    """
    if body.state not in REVIEW_STATES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown review state {body.state!r}",
        )

    notes = body.notes.strip() if body.notes is not None else None
    if body.state == "rejected" and (notes is None or len(notes) < _MIN_REVIEW_NOTES_LENGTH):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "notes are required when rejecting a packet "
                f"(min {_MIN_REVIEW_NOTES_LENGTH} characters)"
            ),
        )

    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    packet.review_state = body.state
    packet.review_notes = notes if notes else None
    packet.review_by_user_id = user.id
    packet.review_transitioned_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(packet)

    files = (
        (await session.execute(select(PacketFile).where(PacketFile.packet_id == packet_id)))
        .scalars()
        .all()
    )
    overrider_name = await _fetch_overrider_name(session, packet)
    return _packet_out(
        packet,
        list(files),
        overrider_name=overrider_name,
        reviewer_name=user.full_name,
    )


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
    reviewer_name = await _fetch_reviewer_name(session, packet)
    return _packet_out(
        packet,
        list(files),
        overrider_name=overrider_name,
        reviewer_name=reviewer_name,
    )


@router.delete("/{packet_id}")
async def delete_packet(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> Response:
    """Permanently delete a packet and all its derived data."""
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    for model in [
        EcvSection, EcvDocument, EcvExtraction,
        ComplianceCheck, ComplianceFinding, ComplianceFeeTolerance, CompliancePacketMetadata,
        IncomeSource, IncomeDtiItem, IncomeFinding, IncomePacketMetadata,
        TitleFlag, TitleProperty, TitleExamException, TitleExamRequirement,
        TitleExamWarning, TitleExamChecklistItem,
        PacketFile,
    ]:
        await session.execute(delete(model).where(model.packet_id == packet_id))

    await session.execute(delete(Packet).where(Packet.id == packet_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    reviewer_name = await _fetch_reviewer_name(session, packet)
    packet_out = _packet_out(
        packet,
        list(files),
        overrider_name=overrider_name,
        reviewer_name=reviewer_name,
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

    scope_set = set(packet.scoped_app_ids or ["ecv"])

    def _item_in_scope(item: EcvLineItem) -> bool:
        # Core checks (no app_ids tag) apply to every packet.
        if not item.app_ids:
            return True
        return any(app_id in scope_set for app_id in item.app_ids)

    # Build line-item outs once; reuse for severity + section score rollups.
    in_scope_items: list[EcvLineItem] = [i for i in line_items if _item_in_scope(i)]

    # Non-ECV apps selected for this packet. When present, only sections with
    # items explicitly tagged for those apps drive the headline score — core
    # ECV items (empty app_ids) remain visible but don't distort the number
    # for use-cases like title-only or income-only packets.
    selected_non_ecv = scope_set - {"ecv"}

    def _item_drives_score(item: EcvLineItem) -> bool:
        """True when this item should contribute to the headline overall_score."""
        if selected_non_ecv:
            # Non-ECV apps selected: only explicitly-tagged items for those apps count.
            return bool(item.app_ids) and any(app_id in scope_set for app_id in item.app_ids)
        # ECV-only packet: all in-scope items count (current behaviour).
        return _item_in_scope(item)

    section_outs: list[EcvSectionOut] = []
    for sec in sections:
        sec_items = items_by_section.get(sec.id, [])
        sec_in_scope_items = [i for i in sec_items if _item_in_scope(i)]
        sec_score_items = [i for i in sec_items if _item_drives_score(i)]
        # Recompute score from in-scope items only. `sec.score` is the
        # original all-items mean, preserved on the row as `raw_score`.
        if sec_in_scope_items:
            score = round(sum(i.confidence for i in sec_in_scope_items) / len(sec_in_scope_items))
        else:
            score = 0
        section_outs.append(
            EcvSectionOut(
                id=str(sec.id),
                section_number=sec.section_number,
                name=sec.name,
                weight=sec.weight,
                score=float(score),
                raw_score=float(sec.score),
                in_scope=bool(sec_in_scope_items),
                drives_score=bool(sec_score_items),
                line_items=[
                    EcvLineItemOut(
                        id=str(i.id),
                        item_code=i.item_code,
                        check=i.check_description,
                        result=i.result_text,
                        confidence=i.confidence,
                        app_ids=list(i.app_ids or []),
                        in_scope=_item_in_scope(i),
                    )
                    for i in sec_items
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

    # Weighted overall score — only sections that drives_score contribute.
    # When non-ECV apps are selected this means only app-tagged sections;
    # for ECV-only packets it degrades gracefully to all in-scope sections.
    weighted_sections = [s for s in section_outs if s.drives_score]
    total_weight = sum(s.weight for s in weighted_sections)
    overall_score = (
        sum(s.score * s.weight for s in weighted_sections) / total_weight
        if total_weight > 0
        else 0.0
    )

    # Severity counts reflect in-scope items only — same logic as overall
    # score. Out-of-scope items still ship to the client (for the
    # collapsed group), they just don't drive red in the header KPIs.
    critical = [i for i in in_scope_items if i.confidence < _CRITICAL_THRESHOLD]
    review = [
        i for i in in_scope_items if _CRITICAL_THRESHOLD <= i.confidence < _CONFIDENCE_THRESHOLD
    ]
    passed = [i for i in in_scope_items if i.confidence >= _CONFIDENCE_THRESHOLD]
    missing_docs = sum(1 for d in documents if d.status == "missing")

    summary = EcvSummaryOut(
        overall_score=round(overall_score, 1),
        auto_approve_threshold=_AUTO_APPROVE_THRESHOLD,
        confidence_threshold=_CONFIDENCE_THRESHOLD,
        critical_threshold=_CRITICAL_THRESHOLD,
        total_items=len(in_scope_items),
        passed_items=len(passed),
        review_items=len(review),
        critical_items=len(critical),
        documents_found=len(documents) - missing_docs,
        documents_missing=missing_docs,
    )

    # Coverage card is "what's currently active for this org" — intersect
    # the packet's stored scope with apps the org is *currently* both
    # subscribed to AND has enabled. ECV is foundational and locked-on,
    # so it's always included even if the row is somehow missing. Apps
    # the customer admin later disabled simply stop appearing here; the
    # rest of the dashboard (sections, line items, documents) is unaffected.
    enabled_subs = {
        row.app_id
        for row in (
            await session.execute(
                select(AppSubscription).where(
                    AppSubscription.org_id == packet.org_id,
                    AppSubscription.enabled.is_(True),
                )
            )
        ).scalars()
    }
    enabled_subs.add("ecv")
    coverage_scope = scope_set & enabled_subs
    coverage = _compute_coverage(coverage_scope, line_items)
    app_gating = await _compute_app_gating(session, packet.org_id, documents)

    return EcvDashboardOut(
        packet=packet_out,
        summary=summary,
        sections=section_outs,
        documents=document_outs,
        app_gating=app_gating,
        coverage=coverage,
    )


def _compute_coverage(
    scope_set: set[str],
    line_items: list[EcvLineItem],
) -> list[AppCoverageOut]:
    """Build per-app coverage rows for every app in the packet's scope.

    For the `ecv` pill, count core (untagged) checks plus items tagged
    `ecv` — ECV is the catch-all bucket. For every other app, count
    ONLY items explicitly tagged for that app, so the per-app score
    reflects that app's specific signal (e.g. Title Examination =
    mean of just title-exam items, not diluted by 41 core ECV checks).
    """
    rows: list[AppCoverageOut] = []
    for app_id in sorted(scope_set):
        if app_id == "ecv":
            app_items = [
                i for i in line_items if not i.app_ids or "ecv" in i.app_ids
            ]
        else:
            app_items = [
                i for i in line_items if i.app_ids and app_id in i.app_ids
            ]
        if not app_items:
            rows.append(
                AppCoverageOut(
                    app_id=app_id,
                    total_items=0,
                    passed_items=0,
                    review_items=0,
                    critical_items=0,
                    score=0.0,
                )
            )
            continue
        passed = sum(1 for i in app_items if i.confidence >= _CONFIDENCE_THRESHOLD)
        review = sum(
            1 for i in app_items if _CRITICAL_THRESHOLD <= i.confidence < _CONFIDENCE_THRESHOLD
        )
        critical = sum(1 for i in app_items if i.confidence < _CRITICAL_THRESHOLD)
        score = round(sum(i.confidence for i in app_items) / len(app_items), 1)
        rows.append(
            AppCoverageOut(
                app_id=app_id,
                total_items=len(app_items),
                passed_items=passed,
                review_items=review,
                critical_items=critical,
                score=score,
            )
        )
    return rows


class EcvExtractionOut(BaseModel):
    """One MISMO 3.6 field extraction with page-level evidence (US-7.3 / 7.4)."""

    id: str
    mismo_path: str
    entity: str
    field: str
    value: str
    confidence: int
    page_number: int | None
    snippet: str | None


class EcvDocumentExtractionsOut(BaseModel):
    """Extractions grouped under the document they were read from.

    `document_id` / `doc_number` / `name` / `mismo_type` mirror the
    `EcvDocumentOut` keys so the MISMO panel can render entity rollups
    without a second round trip. The `unassigned` bucket carries rows
    where `document_id` is NULL (the parent doc was re-classified after
    the extraction ran; see migration 0016's SET NULL rationale).
    """

    document_id: str | None
    doc_number: int | None
    name: str | None
    mismo_type: str | None
    extractions: list[EcvExtractionOut]


class EcvExtractionsOut(BaseModel):
    packet_id: str
    documents: list[EcvDocumentExtractionsOut]


@router.get("/{packet_id}/extractions", response_model=EcvExtractionsOut)
async def get_packet_extractions(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> EcvExtractionsOut:
    """Return every MISMO 3.6 extraction for a packet, grouped by document.

    Powers the MISMO panel (US-7.3) and evidence panel (US-7.4). Returns
    an empty `documents` list rather than 404 when extraction hasn't run
    yet — the panel just renders its empty state; the dashboard's 409 on
    `/ecv` is the correct signal that the packet is still processing.
    RLS scopes every query so a 404 covers both "doesn't exist" and
    "not yours" without leaking existence across tenants.
    """
    packet = (
        await session.execute(select(Packet.id).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

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
    extractions = (
        (
            await session.execute(
                select(EcvExtraction)
                .where(EcvExtraction.packet_id == packet_id)
                .order_by(EcvExtraction.mismo_path)
            )
        )
        .scalars()
        .all()
    )

    by_document: dict[uuid.UUID | None, list[EcvExtraction]] = {}
    for e in extractions:
        by_document.setdefault(e.document_id, []).append(e)

    def _ser(e: EcvExtraction) -> EcvExtractionOut:
        return EcvExtractionOut(
            id=str(e.id),
            mismo_path=e.mismo_path,
            entity=e.entity,
            field=e.field,
            value=e.value,
            confidence=e.confidence,
            page_number=e.page_number,
            snippet=e.snippet,
        )

    groups: list[EcvDocumentExtractionsOut] = []
    for doc in documents:
        rows = by_document.pop(doc.id, [])
        if not rows:
            continue
        groups.append(
            EcvDocumentExtractionsOut(
                document_id=str(doc.id),
                doc_number=doc.doc_number,
                name=doc.name,
                mismo_type=doc.mismo_type,
                extractions=[_ser(r) for r in rows],
            )
        )

    # Anything left is keyed on a document_id that no longer exists or is
    # NULL (SET NULL after re-classification). Surface it explicitly so
    # the UI can still render the data under an "Unassigned" heading.
    orphaned = by_document.get(None, [])
    for doc_id, rows in by_document.items():
        if doc_id is None:
            continue
        orphaned.extend(rows)
    if orphaned:
        groups.append(
            EcvDocumentExtractionsOut(
                document_id=None,
                doc_number=None,
                name=None,
                mismo_type=None,
                extractions=[_ser(r) for r in orphaned],
            )
        )

    return EcvExtractionsOut(packet_id=str(packet_id), documents=groups)


@router.get("/{packet_id}/export/pdf")
async def export_packet_pdf(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> Response:
    """Return the ECV validation report as a PDF (US-8.1).

    Loads the same objects `GET /api/packets/{id}/ecv` returns and hands
    them to the rendering module. RLS scopes every query, so a 404
    covers both "doesn't exist" and "not yours" — identical to the
    dashboard endpoint. 409 when the stub hasn't reached the `score`
    stage yet, because a PDF with no findings is worse than no PDF.
    """
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

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

    overrider_name = await _fetch_overrider_name(session, packet)
    reviewer_name = await _fetch_reviewer_name(session, packet)

    pdf_bytes = render_ecv_pdf(
        packet=packet,
        sections=sections,
        line_items=line_items,
        documents=documents,
        overrider_name=overrider_name,
        reviewer_name=reviewer_name,
    )

    short_id = str(packet.id)[:8]
    filename = f"ecv-report-{short_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{packet_id}/export/mismo")
async def export_packet_mismo(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> Response:
    """Return the ECV payload as MISMO 3.6 XML (US-8.2).

    Shares query plumbing with the PDF endpoint — same RLS guarantees
    (404 on cross-org), same 409 when findings haven't landed yet, same
    serialization of the ORM objects into the renderer. Media type is
    `application/xml`; browsers treat that as a download with the
    Content-Disposition below.
    """
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

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

    reviewer_name = await _fetch_reviewer_name(session, packet)

    xml_bytes = render_ecv_mismo_xml(
        packet=packet,
        sections=sections,
        line_items=line_items,
        documents=documents,
        reviewer_name=reviewer_name,
    )

    short_id = str(packet.id)[:8]
    filename = f"ecv-mismo-{short_id}.xml"
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
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
