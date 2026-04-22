"""Title Search & Abstraction micro-app API (US-6.1).

`GET /api/packets/{id}/title-search` — returns the full Title Search
payload for a packet in one round trip: severity rollup, 7 risk flags
(each with AI recommendation, MISMO extractions, source evidence, and
optional cross-app reference), and the property summary document
(identification → physical → chain of title → mortgages / liens /
easements / taxes / title insurance).

Requires an active, enabled subscription to the `title-search` app —
the ECV launcher only routes here when the app is ready, but we enforce
the gate server-side too so a deep-linked URL can't skip it. RLS scopes
every query, so a 404 covers both "doesn't exist" and "not yours"
without leaking existence across tenants.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_customer_role
from app.models import (
    AppSubscription,
    Packet,
    TitleFlag,
    TitleProperty,
    User,
)

router = APIRouter(prefix="/api/packets", tags=["title-search"])


class MismoFieldOut(BaseModel):
    entity: str
    field: str
    value: str
    confidence: int


class AiRecommendationOut(BaseModel):
    decision: str
    confidence: int
    reasoning: str


class SourceOut(BaseModel):
    doc_type: str
    pages: list[int]


class EvidenceOut(BaseModel):
    page: int
    snippet: str


class CrossAppRefOut(BaseModel):
    app: str
    section: str
    note: str


class TitleFlagOut(BaseModel):
    id: str
    number: int
    severity: str
    flag_type: str
    title: str
    description: str
    page_ref: str
    ai_note: str | None
    ai_rec: AiRecommendationOut | None
    mismo: list[MismoFieldOut]
    source: SourceOut
    cross_app: CrossAppRefOut | None
    evidence: list[EvidenceOut]


class SeverityCountsOut(BaseModel):
    """Count of flags per severity bucket — drives the risk summary cards."""

    critical: int
    high: int
    medium: int
    low: int
    total: int


class TitleSearchDashboardOut(BaseModel):
    severity_counts: SeverityCountsOut
    flags: list[TitleFlagOut]
    property_summary: dict[str, Any]


@router.get("/{packet_id}/title-search", response_model=TitleSearchDashboardOut)
async def get_packet_title_search(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> TitleSearchDashboardOut:
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    sub = (
        await session.execute(
            select(AppSubscription).where(
                AppSubscription.org_id == packet.org_id,
                AppSubscription.app_id == "title-search",
            )
        )
    ).scalar_one_or_none()
    if sub is None or not sub.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="title-search app not enabled for this org",
        )

    flags = (
        (
            await session.execute(
                select(TitleFlag)
                .where(TitleFlag.packet_id == packet_id)
                .order_by(TitleFlag.sort_order)
            )
        )
        .scalars()
        .all()
    )
    if not flags:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="title-search findings not ready yet",
        )

    property_row = (
        await session.execute(select(TitleProperty).where(TitleProperty.packet_id == packet_id))
    ).scalar_one_or_none()

    flag_outs = [
        TitleFlagOut(
            id=str(f.id),
            number=f.flag_number,
            severity=f.severity,
            flag_type=f.flag_type,
            title=f.title,
            description=f.description,
            page_ref=f.page_ref,
            ai_note=f.ai_note,
            ai_rec=(
                AiRecommendationOut(
                    decision=f.ai_rec_decision,
                    confidence=f.ai_rec_confidence or 0,
                    reasoning=f.ai_rec_reasoning or "",
                )
                if f.ai_rec_decision is not None
                else None
            ),
            mismo=[
                MismoFieldOut(
                    entity=m.get("entity", ""),
                    field=m.get("field", ""),
                    value=m.get("value", ""),
                    confidence=int(m.get("confidence", 0)),
                )
                for m in (f.mismo_fields or [])
            ],
            source=SourceOut(
                doc_type=(f.source or {}).get("doc_type", ""),
                pages=list((f.source or {}).get("pages", [])),
            ),
            cross_app=(
                CrossAppRefOut(
                    app=f.cross_app.get("app", ""),
                    section=f.cross_app.get("section", ""),
                    note=f.cross_app.get("note", ""),
                )
                if f.cross_app
                else None
            ),
            evidence=[
                EvidenceOut(
                    page=int(e.get("page", 0)),
                    snippet=e.get("snippet", ""),
                )
                for e in (f.evidence or [])
            ],
        )
        for f in flags
    ]

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in flags:
        if f.severity in counts:
            counts[f.severity] += 1
    severity_counts = SeverityCountsOut(
        critical=counts["critical"],
        high=counts["high"],
        medium=counts["medium"],
        low=counts["low"],
        total=len(flags),
    )

    return TitleSearchDashboardOut(
        severity_counts=severity_counts,
        flags=flag_outs,
        property_summary=(property_row.summary if property_row is not None else {}),
    )
