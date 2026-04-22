"""Title Examination micro-app API (US-6.2).

Two endpoints:

- `GET /api/packets/{id}/title-exam` — returns the full Title Exam
  payload: Schedule B (standard + specific exceptions), Schedule C
  requirements, examiner warnings, and the curative checklist with
  completion state.

- `PATCH /api/packets/{id}/title-exam/checklist/{item_id}` — toggles a
  single checklist item's `checked` state. This is the curative-
  workflow state primitive — the Phase 6 "state machine" for title
  exam is a simple per-item boolean driven by the underwriter.

Both require an active, enabled subscription to the `title-exam` app;
the ECV launcher only routes here when ready, but we re-check server-
side so deep links can't skip the gate. RLS scopes reads and the PATCH
writes go through a tenant-context session so the underwriter can
only mutate rows in their own org.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_customer_role
from app.models import (
    TITLE_EXAM_FLAG_KINDS,
    TITLE_EXAM_FLAG_STATUSES,
    TITLE_EXAM_REVIEW_DECISIONS,
    AppSubscription,
    Packet,
    TitleExamChecklistItem,
    TitleExamException,
    TitleExamRequirement,
    TitleExamReview,
    TitleExamWarning,
    User,
)

router = APIRouter(prefix="/api/packets", tags=["title-exam"])


class ReviewOut(BaseModel):
    """One reviewer decision on a flag — mirrors TI Hub's ReviewResponse."""

    id: str
    flag_id: str
    flag_kind: Literal["exception", "warning"]
    reviewer_id: str
    decision: str
    reason_code: str
    notes: str | None
    created_at: datetime


class ExceptionOut(BaseModel):
    """Schedule B exception — superset of TI Hub's ExaminerFlag.

    `flag_type`, `ai_explanation`, `evidence_refs`, `status`, and `reviews`
    mirror the TI Hub shape so downstream consumers can treat the output
    interchangeably.
    """

    id: str
    schedule: Literal["standard", "specific"]
    number: int
    severity: str
    title: str
    description: str
    page_ref: str | None
    note: str | None
    # TI Hub superset fields.
    flag_type: str | None = None
    ai_explanation: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "open"
    reviews: list[ReviewOut] = Field(default_factory=list)


class RequirementOut(BaseModel):
    id: str
    number: int
    title: str
    priority: str
    status: str
    page_ref: str | None
    description: str
    note: str | None
    # Transparency fields — requirements don't carry flag_type/status/reviews
    # (those are flag-specific) but do carry explanation + evidence.
    ai_explanation: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class WarningOut(BaseModel):
    """Examiner warning — treated as a flag in TI Hub vocabulary."""

    id: str
    severity: str
    title: str
    description: str
    note: str | None
    flag_type: str | None = None
    ai_explanation: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "open"
    reviews: list[ReviewOut] = Field(default_factory=list)


class ReviewCreate(BaseModel):
    """Payload for POST /title-exam/flags/{kind}/{id}/reviews.

    Shape matches TI Hub's ReviewCreate so clients can reuse the same
    serialization.
    """

    decision: Literal["approve", "reject", "escalate"]
    reason_code: str = ""
    notes: str | None = None


class SeverityBreakdown(BaseModel):
    """Severity → count. Shape matches TI Hub's FlagListResponse.counts."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class RecommendationResponse(BaseModel):
    """Aggregate AI recommendation across all title-exam flags.

    Mirrors TI Hub's RecommendationResponse — (decision, reasoning,
    confidence). Deterministic rollup from the seeded findings; in
    production this would come from the LLM reasoning layer.
    """

    decision: Literal["approve", "reject", "escalate"]
    reasoning: str
    confidence: float


class ChecklistItemOut(BaseModel):
    id: str
    number: int
    action: str
    priority: str
    checked: bool
    note: str | None


class SeverityCountsOut(BaseModel):
    critical: int
    high: int
    medium: int
    low: int
    total: int


class ChecklistProgressOut(BaseModel):
    completed: int
    total: int


class TitleExamDashboardOut(BaseModel):
    severity_counts: SeverityCountsOut
    standard_exceptions: list[ExceptionOut]
    specific_exceptions: list[ExceptionOut]
    requirements: list[RequirementOut]
    warnings: list[WarningOut]
    checklist: list[ChecklistItemOut]
    checklist_progress: ChecklistProgressOut


class ChecklistTogglePayload(BaseModel):
    checked: bool


async def _require_subscription(session: AsyncSession, packet_id: uuid.UUID) -> Packet:
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    sub = (
        await session.execute(
            select(AppSubscription).where(
                AppSubscription.org_id == packet.org_id,
                AppSubscription.app_id == "title-exam",
            )
        )
    ).scalar_one_or_none()
    if sub is None or not sub.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="title-exam app not enabled for this org",
        )
    return packet


@router.get("/{packet_id}/title-exam", response_model=TitleExamDashboardOut)
async def get_packet_title_exam(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> TitleExamDashboardOut:
    await _require_subscription(session, packet_id)

    exceptions = (
        (
            await session.execute(
                select(TitleExamException)
                .where(TitleExamException.packet_id == packet_id)
                .order_by(TitleExamException.sort_order)
            )
        )
        .scalars()
        .all()
    )
    if not exceptions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="title-exam findings not ready yet",
        )

    requirements = (
        (
            await session.execute(
                select(TitleExamRequirement)
                .where(TitleExamRequirement.packet_id == packet_id)
                .order_by(TitleExamRequirement.sort_order)
            )
        )
        .scalars()
        .all()
    )
    warnings = (
        (
            await session.execute(
                select(TitleExamWarning)
                .where(TitleExamWarning.packet_id == packet_id)
                .order_by(TitleExamWarning.sort_order)
            )
        )
        .scalars()
        .all()
    )
    checklist = (
        (
            await session.execute(
                select(TitleExamChecklistItem)
                .where(TitleExamChecklistItem.packet_id == packet_id)
                .order_by(TitleExamChecklistItem.sort_order)
            )
        )
        .scalars()
        .all()
    )

    # Hydrate reviews for every flag (exception + warning). One query
    # instead of N — bucket by (kind, flag_id) for O(1) lookup below.
    review_rows = (
        (
            await session.execute(
                select(TitleExamReview)
                .where(TitleExamReview.packet_id == packet_id)
                .order_by(TitleExamReview.created_at)
            )
        )
        .scalars()
        .all()
    )
    reviews_by_flag: dict[tuple[str, uuid.UUID], list[ReviewOut]] = {}
    for rv in review_rows:
        key = (rv.flag_kind, rv.flag_id)
        reviews_by_flag.setdefault(key, []).append(
            ReviewOut(
                id=str(rv.id),
                flag_id=str(rv.flag_id),
                flag_kind=rv.flag_kind,  # type: ignore[arg-type]
                reviewer_id=str(rv.reviewer_id),
                decision=rv.decision,
                reason_code=rv.reason_code,
                notes=rv.notes,
                created_at=rv.created_at,
            )
        )

    def _exception_out(e: TitleExamException) -> ExceptionOut:
        return ExceptionOut(
            id=str(e.id),
            schedule=e.schedule,  # type: ignore[arg-type]
            number=e.exception_number,
            severity=e.severity,
            title=e.title,
            description=e.description,
            page_ref=e.page_ref,
            note=e.note,
            flag_type=e.flag_type,
            ai_explanation=e.ai_explanation,
            evidence_refs=list(e.evidence_refs or []),
            status=e.status,
            reviews=reviews_by_flag.get(("exception", e.id), []),
        )

    standard_outs = [_exception_out(e) for e in exceptions if e.schedule == "standard"]
    specific_outs = [_exception_out(e) for e in exceptions if e.schedule == "specific"]

    # Severity rollup is computed across specific exceptions only — the
    # standard ones are boilerplate ALTA exceptions, not risk findings.
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for e in exceptions:
        if e.schedule == "specific" and e.severity in counts:
            counts[e.severity] += 1
    severity_counts = SeverityCountsOut(
        critical=counts["critical"],
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
        total=sum(counts.values()),
    )

    checklist_outs = [
        ChecklistItemOut(
            id=str(c.id),
            number=c.item_number,
            action=c.action,
            priority=c.priority,
            checked=c.checked,
            note=c.note,
        )
        for c in checklist
    ]

    progress = ChecklistProgressOut(
        completed=sum(1 for c in checklist if c.checked),
        total=len(checklist),
    )

    return TitleExamDashboardOut(
        severity_counts=severity_counts,
        standard_exceptions=standard_outs,
        specific_exceptions=specific_outs,
        requirements=[
            RequirementOut(
                id=str(r.id),
                number=r.requirement_number,
                title=r.title,
                priority=r.priority,
                status=r.status,
                page_ref=r.page_ref,
                description=r.description,
                note=r.note,
                ai_explanation=r.ai_explanation,
                evidence_refs=list(r.evidence_refs or []),
            )
            for r in requirements
        ],
        warnings=[
            WarningOut(
                id=str(w.id),
                severity=w.severity,
                title=w.title,
                description=w.description,
                note=w.note,
                flag_type=w.flag_type,
                ai_explanation=w.ai_explanation,
                evidence_refs=list(w.evidence_refs or []),
                status=w.status,
                reviews=reviews_by_flag.get(("warning", w.id), []),
            )
            for w in warnings
        ],
        checklist=checklist_outs,
        checklist_progress=progress,
    )


@router.patch(
    "/{packet_id}/title-exam/checklist/{item_id}",
    response_model=ChecklistItemOut,
)
async def toggle_checklist_item(
    packet_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ChecklistTogglePayload,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> ChecklistItemOut:
    await _require_subscription(session, packet_id)

    item = (
        await session.execute(
            select(TitleExamChecklistItem).where(
                TitleExamChecklistItem.id == item_id,
                TitleExamChecklistItem.packet_id == packet_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="checklist item not found"
        )

    item.checked = payload.checked
    item.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(item)

    return ChecklistItemOut(
        id=str(item.id),
        number=item.item_number,
        action=item.action,
        priority=item.priority,
        checked=item.checked,
        note=item.note,
    )


# ═══════════════════════════════════════════════════════════════════════
# TI Hub-parity endpoints — per-flag review workflow + aggregate
# recommendation. Mirrors title_intelligence_hub's flag router surface.
# ═══════════════════════════════════════════════════════════════════════


# Status transition applied when a reviewer records a decision. Approve +
# reject close the flag; escalate marks it reviewed-but-not-closed so a
# senior reviewer can take over without the row disappearing from queues.
_DECISION_TO_STATUS: dict[str, str] = {
    "approve": "closed",
    "reject": "closed",
    "escalate": "reviewed",
}


async def _load_flag(
    session: AsyncSession,
    packet_id: uuid.UUID,
    flag_kind: str,
    flag_id: uuid.UUID,
) -> TitleExamException | TitleExamWarning:
    """Fetch the flag row by (kind, id) and verify it belongs to the packet.

    Raises 404 if the kind is unknown, the row doesn't exist, or the row
    belongs to a different packet — same shape as any cross-resource
    lookup failure.
    """
    if flag_kind not in TITLE_EXAM_FLAG_KINDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="flag not found")

    if flag_kind == "exception":
        row: TitleExamException | TitleExamWarning | None = (
            await session.execute(
                select(TitleExamException).where(
                    TitleExamException.id == flag_id,
                    TitleExamException.packet_id == packet_id,
                )
            )
        ).scalar_one_or_none()
    else:
        row = (
            await session.execute(
                select(TitleExamWarning).where(
                    TitleExamWarning.id == flag_id,
                    TitleExamWarning.packet_id == packet_id,
                )
            )
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="flag not found")
    return row


@router.post(
    "/{packet_id}/title-exam/flags/{flag_kind}/{flag_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_flag_review(
    packet_id: uuid.UUID,
    flag_kind: Literal["exception", "warning"],
    flag_id: uuid.UUID,
    payload: ReviewCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> ReviewOut:
    """Record one reviewer decision on a flag.

    - Verifies the packet is subscribed to title-exam.
    - Verifies the flag exists and belongs to the packet (404 otherwise,
      matching RLS-shaped behavior).
    - Inserts a review row + transitions the flag's `status` per
      `_DECISION_TO_STATUS`.

    Mirrors TI Hub's POST /flags/{id}/reviews — the one difference is
    `flag_kind` in the path because title-exam flags live in two tables.
    """
    await _require_subscription(session, packet_id)

    flag = await _load_flag(session, packet_id, flag_kind, flag_id)
    # RLS also hides cross-org rows, but an explicit org check keeps the
    # 404 behavior even when a platform-admin session is bypassing RLS.
    if flag.org_id != user.org_id and user.role != "platform_admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="flag not found")

    review = TitleExamReview(
        packet_id=packet_id,
        org_id=flag.org_id,
        flag_kind=flag_kind,
        flag_id=flag_id,
        reviewer_id=user.id,
        decision=payload.decision,
        reason_code=payload.reason_code or "",
        notes=payload.notes,
    )
    session.add(review)

    # Transition flag lifecycle so subsequent dashboard loads reflect the
    # decision without an additional lookup on the client.
    new_status = _DECISION_TO_STATUS[payload.decision]
    if new_status not in TITLE_EXAM_FLAG_STATUSES:  # defensive — kept in sync
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="invalid flag status transition",
        )
    flag.status = new_status

    await session.commit()
    await session.refresh(review)

    return ReviewOut(
        id=str(review.id),
        flag_id=str(review.flag_id),
        flag_kind=review.flag_kind,  # type: ignore[arg-type]
        reviewer_id=str(review.reviewer_id),
        decision=review.decision,
        reason_code=review.reason_code,
        notes=review.notes,
        created_at=review.created_at,
    )


@router.get(
    "/{packet_id}/title-exam/recommendation",
    response_model=RecommendationResponse,
)
async def get_title_exam_recommendation(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> RecommendationResponse:
    """Aggregate AI recommendation across the packet's title-exam flags.

    Deterministic rollup: any *open* critical finding → `reject`; else any
    *open* high finding → `escalate`; otherwise → `approve`. Closed flags
    are excluded so recording reviews materially moves the recommendation.
    Mirrors TI Hub's RecommendationResponse shape so consumers stay
    source-agnostic. In production this would be the Claude reasoning
    layer's output; here it's a faithful stand-in.
    """
    await _require_subscription(session, packet_id)

    specific_exceptions = (
        (
            await session.execute(
                select(TitleExamException).where(
                    TitleExamException.packet_id == packet_id,
                    TitleExamException.schedule == "specific",
                )
            )
        )
        .scalars()
        .all()
    )
    warnings = (
        (
            await session.execute(
                select(TitleExamWarning).where(TitleExamWarning.packet_id == packet_id)
            )
        )
        .scalars()
        .all()
    )

    # Build "open flags" set — closed ones no longer count toward the
    # aggregate because the reviewer has dispositioned them.
    open_flags = [f for f in list(specific_exceptions) + list(warnings) if f.status != "closed"]

    critical = sum(1 for f in open_flags if f.severity == "critical")
    high = sum(1 for f in open_flags if f.severity == "high")

    if critical > 0:
        return RecommendationResponse(
            decision="reject",
            reasoning=(
                f"{critical} open critical title finding(s) — title cannot "
                "convey free and clear until the underlying defects are "
                "cured."
            ),
            confidence=0.95,
        )
    if high > 0:
        return RecommendationResponse(
            decision="escalate",
            reasoning=(
                f"{high} open high-severity title finding(s) requiring "
                "senior underwriter review before the policy issues."
            ),
            confidence=0.80,
        )
    return RecommendationResponse(
        decision="approve",
        reasoning=(
            "No open critical or high-severity title findings remain after reviewer dispositions."
        ),
        confidence=0.90,
    )


# Re-export the review-decision vocabulary so tests can assert against the
# same enum the router validates — keeps the taxonomy single-sourced.
__all__ = [
    "TITLE_EXAM_REVIEW_DECISIONS",
    "router",
]
