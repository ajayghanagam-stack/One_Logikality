"""Compliance micro-app API (US-6.3).

`GET /api/packets/{id}/compliance` — returns the full compliance payload
for a packet in one round trip: per-check verdicts (C-01 through C-10),
the TRID fee-tolerance table (Zero / 10% / Unlimited), and a top-line
summary the Overview tab renders without recomputing.

Requires an active, enabled subscription to the `compliance` app — the
ECV launcher only routes here when the app is ready, but we enforce
gating server-side too so a deep-linked URL can't skip the check. RLS
scopes every query, so a 404 covers both "doesn't exist" and "not yours"
without leaking existence across tenants.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_customer_role
from app.models import (
    AppSubscription,
    ComplianceCheck,
    ComplianceFeeTolerance,
    Packet,
    User,
)

router = APIRouter(prefix="/api/packets", tags=["compliance"])


class MismoFieldOut(BaseModel):
    """One MISMO 3.6 extraction supporting a compliance check."""

    entity: str
    field: str
    value: str
    confidence: int


class ComplianceCheckOut(BaseModel):
    id: str
    check_code: str
    category: str
    rule: str
    status: str
    detail: str
    ai_note: str | None
    mismo: list[MismoFieldOut]


class FeeToleranceOut(BaseModel):
    id: str
    bucket: str
    le: str
    cd: str
    diff: str
    pct: str
    status: str


class ComplianceSummaryOut(BaseModel):
    """Top-line counts the Overview tab renders without recomputing."""

    total_checks: int
    passed: int
    failed: int
    warned: int
    not_applicable: int
    # Score = passed / (total - n/a), rounded to int. Matches demo rollup.
    score: int


class ComplianceDashboardOut(BaseModel):
    summary: ComplianceSummaryOut
    checks: list[ComplianceCheckOut]
    fee_tolerances: list[FeeToleranceOut]


@router.get("/{packet_id}/compliance", response_model=ComplianceDashboardOut)
async def get_packet_compliance(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> ComplianceDashboardOut:
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    # Subscription gate — the ECV launcher filters blocked apps out of
    # the UI, but we re-check here so a direct URL can't skip gating.
    # Unsubscribed / disabled → 403 so the frontend can surface a clear
    # "not available" state rather than a generic 404.
    sub = (
        await session.execute(
            select(AppSubscription).where(
                AppSubscription.org_id == packet.org_id,
                AppSubscription.app_id == "compliance",
            )
        )
    ).scalar_one_or_none()
    if sub is None or not sub.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="compliance app not enabled for this org",
        )

    checks = (
        (
            await session.execute(
                select(ComplianceCheck)
                .where(ComplianceCheck.packet_id == packet_id)
                .order_by(ComplianceCheck.check_code)
            )
        )
        .scalars()
        .all()
    )
    if not checks:
        # Pipeline hasn't reached the `score` stage yet — the Compliance
        # page should poll or redirect back to the ECV dashboard until
        # findings land.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="compliance findings not ready yet",
        )

    tolerances = (
        (
            await session.execute(
                select(ComplianceFeeTolerance)
                .where(ComplianceFeeTolerance.packet_id == packet_id)
                .order_by(ComplianceFeeTolerance.sort_order)
            )
        )
        .scalars()
        .all()
    )

    check_outs = [
        ComplianceCheckOut(
            id=str(c.id),
            check_code=c.check_code,
            category=c.category,
            rule=c.rule,
            status=c.status,
            detail=c.detail,
            ai_note=c.ai_note,
            mismo=[
                MismoFieldOut(
                    entity=f.get("entity", ""),
                    field=f.get("field", ""),
                    value=f.get("value", ""),
                    confidence=int(f.get("confidence", 0)),
                )
                for f in (c.mismo_fields or [])
            ],
        )
        for c in checks
    ]

    tolerance_outs = [
        FeeToleranceOut(
            id=str(t.id),
            bucket=t.bucket,
            le=t.le_amount,
            cd=t.cd_amount,
            diff=t.diff_amount,
            pct=t.variance_pct,
            status=t.status,
        )
        for t in tolerances
    ]

    passed = sum(1 for c in checks if c.status == "pass")
    failed = sum(1 for c in checks if c.status == "fail")
    warned = sum(1 for c in checks if c.status == "warn")
    na = sum(1 for c in checks if c.status == "n/a")
    denom = len(checks) - na
    # Demo rolls compliance score as passed / (total - n/a). All-n/a
    # packets (hypothetical) get a 0 score rather than a divide-by-zero.
    score = round((passed / denom) * 100) if denom > 0 else 0

    summary = ComplianceSummaryOut(
        total_checks=len(checks),
        passed=passed,
        failed=failed,
        warned=warned,
        not_applicable=na,
        score=score,
    )

    return ComplianceDashboardOut(
        summary=summary,
        checks=check_outs,
        fee_tolerances=tolerance_outs,
    )
