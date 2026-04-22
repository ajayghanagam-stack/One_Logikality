"""Income Calculation micro-app API (US-6.4).

`GET /api/packets/{id}/income` — returns the full Income Calculation
payload for a packet in one round trip. Response shape is a strict
superset of the TI-parity `IncomeCalculationOutput` TypeScript
interface: per-borrower employment / non-employment sources with VOE +
MISMO 3.6 field paths + stated-vs-verified variance, packet-level
combined metrics (front-end / back-end DTI + dtiStatus), appliedRules
bundle, optional VA residual-income block, findings array, packet-level
evidence trace, and an overall confidence score. Legacy top-level
fields (`sources`, `dti_items`, `summary`) are kept for the existing
frontend surface — new callers should consume `borrowers`, `combined`,
`appliedRules`, etc.

Requires an active, enabled subscription to the `income-calc` app — the
ECV launcher only routes here when the app is ready, but we enforce the
gate server-side too so a deep-linked URL can't skip it. RLS scopes
every query, so a 404 covers both "doesn't exist" and "not yours"
without leaking existence across tenants.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import require_customer_role
from app.models import (
    AppSubscription,
    IncomeDtiItem,
    IncomeFinding,
    IncomePacketMetadata,
    IncomeSource,
    Packet,
    User,
)

router = APIRouter(prefix="/api/packets", tags=["income"])


# ---------------------------------------------------------------------------
# Legacy schemas (kept for existing frontend surface).
# ---------------------------------------------------------------------------


class MismoFieldOut(BaseModel):
    """One MISMO 3.6 extraction supporting an income source."""

    entity: str
    field: str
    value: str
    confidence: int


class IncomeSourceOut(BaseModel):
    id: str
    source_code: str
    source_name: str
    employer: str | None
    position: str | None
    income_type: str
    monthly: float
    annual: float
    trend: str
    years: float
    confidence: int
    ai_note: str | None
    mismo: list[MismoFieldOut]
    docs: list[str]


class DtiItemOut(BaseModel):
    id: str
    description: str
    monthly: float


class IncomeSummaryOut(BaseModel):
    """Top-line rollup the Overview + DTI tabs render without recomputing."""

    total_monthly: float
    total_annual: float
    total_debt: float
    dti: float
    source_count: int


# ---------------------------------------------------------------------------
# TI-parity schemas — one-to-one with the target TS interfaces.
# ---------------------------------------------------------------------------


class MismoPathsOut(BaseModel):
    employer_path: str
    income_path: str


class VoeOut(BaseModel):
    type: str
    date: str


class TrendingBlockOut(BaseModel):
    amount: float
    method: str
    trending: str


class MethodBlockOut(BaseModel):
    amount: float
    method: str


class EmploymentSourceOut(BaseModel):
    """TI-parity per-source breakdown (`EmploymentIncomeSource` +
    non-employment; the frontend renders the two via different cards).
    """

    source_code: str
    employer: str | None
    employment_type: str | None
    start_date: str | None
    tenure: dict[str, int]
    base_salary: float | None
    overtime: TrendingBlockOut | None
    bonus: MethodBlockOut | None
    commission: MethodBlockOut | None
    total_qualifying: float
    voe: VoeOut | None
    sources: list[str]  # docs
    mismo: MismoPathsOut | None
    trend: str
    confidence: int


class NonEmploymentSourceOut(BaseModel):
    source_code: str
    source_name: str
    income_type: str
    monthly: float
    annual: float
    trend: str
    confidence: int
    sources: list[str]
    mismo: MismoPathsOut | None


class BorrowerIncomeOut(BaseModel):
    borrower_id: str
    name: str
    employment_sources: list[EmploymentSourceOut]
    non_employment_sources: list[NonEmploymentSourceOut]
    qualifying_monthly_income: float
    stated_monthly_income: float
    verified_monthly_income: float
    variance: float


class CombinedOut(BaseModel):
    total_monthly_qualifying_income: float
    total_monthly_obligations: float
    front_end_dti: float
    back_end_dti: float
    dti_status: str  # within_limit | above_limit | compensating_factors_required


class AppliedRulesOut(BaseModel):
    program_id: str
    dti_limit: float
    guidelines: str
    trending_method: str
    residual_income_required: bool


class ResidualIncomeOut(BaseModel):
    net_monthly_income: float
    total_obligations: float
    residual: float
    regional_table: str
    required_residual: float
    meets_requirement: bool


class IncomeFindingOut(BaseModel):
    finding_id: str
    severity: str
    category: str
    description: str
    recommendation: str
    affected_sources: list[str]
    mismo_refs: list[str]


class EvidenceTraceOut(BaseModel):
    document_id: str
    page: int
    mismo_path: str
    snippet: str


class IncomeDashboardOut(BaseModel):
    # Legacy surface — unchanged.
    summary: IncomeSummaryOut
    sources: list[IncomeSourceOut]
    dti_items: list[DtiItemOut]
    # TI-parity superset.
    packet_id: str
    borrowers: list[BorrowerIncomeOut] = Field(default_factory=list)
    combined: CombinedOut
    applied_rules: AppliedRulesOut
    residual_income: ResidualIncomeOut | None = None
    findings: list[IncomeFindingOut] = Field(default_factory=list)
    evidence: list[EvidenceTraceOut] = Field(default_factory=list)
    confidence: int


def _dti_status(back_end: float, limit: float) -> str:
    """Classify the back-end DTI against the program limit.

    Matches the `dtiStatus` enum in the target interface: within_limit
    when the ratio is at or below the limit, above_limit when it strictly
    exceeds it, compensating_factors_required in the 2pp warning band just
    beyond. Values are in percentage points (e.g. 45.0).
    """
    if back_end <= limit:
        return "within_limit"
    if back_end <= limit + 2.0:
        return "compensating_factors_required"
    return "above_limit"


def _safe_float(v: Any, default: float = 0.0) -> float:
    """Coerce a JSONB-serialized Decimal string (or number) to float."""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _build_employment_source(s: IncomeSource) -> EmploymentSourceOut:
    overtime = None
    if s.overtime:
        overtime = TrendingBlockOut(
            amount=_safe_float(s.overtime.get("amount")),
            method=s.overtime.get("method", "averaged"),
            trending=s.overtime.get("trending", "stable"),
        )
    bonus = None
    if s.bonus:
        bonus = MethodBlockOut(
            amount=_safe_float(s.bonus.get("amount")),
            method=s.bonus.get("method", "averaged"),
        )
    commission = None
    if s.commission:
        commission = MethodBlockOut(
            amount=_safe_float(s.commission.get("amount")),
            method=s.commission.get("method", "averaged"),
        )
    voe = None
    if s.voe:
        voe = VoeOut(type=s.voe.get("type", "none"), date=s.voe.get("date", ""))
    mismo = None
    if s.mismo_paths:
        mismo = MismoPathsOut(
            employer_path=s.mismo_paths.get("employer_path", ""),
            income_path=s.mismo_paths.get("income_path", ""),
        )
    return EmploymentSourceOut(
        source_code=s.source_code,
        employer=s.employer,
        employment_type=s.employment_type,
        start_date=s.start_date.isoformat() if s.start_date else None,
        tenure={
            "years": s.tenure_years or 0,
            "months": s.tenure_months or 0,
        },
        base_salary=float(s.base_salary) if s.base_salary is not None else None,
        overtime=overtime,
        bonus=bonus,
        commission=commission,
        total_qualifying=float(s.total_qualifying)
        if s.total_qualifying is not None
        else float(s.monthly_amount),
        voe=voe,
        sources=list(s.docs or []),
        mismo=mismo,
        trend=s.trend,
        confidence=s.confidence,
    )


def _build_non_employment_source(s: IncomeSource) -> NonEmploymentSourceOut:
    mismo = None
    if s.mismo_paths:
        mismo = MismoPathsOut(
            employer_path=s.mismo_paths.get("employer_path", ""),
            income_path=s.mismo_paths.get("income_path", ""),
        )
    return NonEmploymentSourceOut(
        source_code=s.source_code,
        source_name=s.source_name,
        income_type=s.income_type,
        monthly=float(s.monthly_amount),
        annual=float(s.annual_amount),
        trend=s.trend,
        confidence=s.confidence,
        sources=list(s.docs or []),
        mismo=mismo,
    )


def _build_borrowers(sources: Iterable[IncomeSource]) -> list[BorrowerIncomeOut]:
    """Partition sources by borrower + employment category.

    Rows that predate migration 0015 (no borrower_id / category) are
    bucketed under a synthetic "primary borrower" with every source
    treated as employment — keeps the endpoint 200 even when the seed
    hasn't been rerun.
    """
    by_borrower: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "name": "Primary Borrower",
            "employment": [],
            "non_employment": [],
            "qualifying": Decimal("0"),
            "stated": Decimal("0"),
            "verified": Decimal("0"),
        }
    )
    for s in sources:
        bid = s.borrower_id or "borrower_1"
        slot = by_borrower[bid]
        if s.borrower_name:
            slot["name"] = s.borrower_name
        category = s.category or "employment"
        if category == "non_employment":
            slot["non_employment"].append(_build_non_employment_source(s))
        else:
            slot["employment"].append(_build_employment_source(s))
        # Qualifying monthly == total_qualifying when set, else monthly_amount.
        qualifying = (
            Decimal(s.total_qualifying)
            if s.total_qualifying is not None
            else Decimal(s.monthly_amount)
        )
        slot["qualifying"] += qualifying
        stated = (
            Decimal(s.stated_monthly) if s.stated_monthly is not None else Decimal(s.monthly_amount)
        )
        verified = (
            Decimal(s.verified_monthly)
            if s.verified_monthly is not None
            else Decimal(s.monthly_amount)
        )
        slot["stated"] += stated
        slot["verified"] += verified

    return [
        BorrowerIncomeOut(
            borrower_id=bid,
            name=slot["name"],
            employment_sources=slot["employment"],
            non_employment_sources=slot["non_employment"],
            qualifying_monthly_income=float(slot["qualifying"]),
            stated_monthly_income=float(slot["stated"]),
            verified_monthly_income=float(slot["verified"]),
            variance=float(slot["stated"] - slot["verified"]),
        )
        for bid, slot in by_borrower.items()
    ]


@router.get("/{packet_id}/income", response_model=IncomeDashboardOut)
async def get_packet_income(
    packet_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(require_customer_role)],
) -> IncomeDashboardOut:
    packet = (
        await session.execute(select(Packet).where(Packet.id == packet_id))
    ).scalar_one_or_none()
    if packet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="packet not found")

    sub = (
        await session.execute(
            select(AppSubscription).where(
                AppSubscription.org_id == packet.org_id,
                AppSubscription.app_id == "income-calc",
            )
        )
    ).scalar_one_or_none()
    if sub is None or not sub.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="income-calc app not enabled for this org",
        )

    sources = (
        (
            await session.execute(
                select(IncomeSource)
                .where(IncomeSource.packet_id == packet_id)
                .order_by(IncomeSource.sort_order)
            )
        )
        .scalars()
        .all()
    )
    if not sources:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="income findings not ready yet",
        )

    dti_items = (
        (
            await session.execute(
                select(IncomeDtiItem)
                .where(IncomeDtiItem.packet_id == packet_id)
                .order_by(IncomeDtiItem.sort_order)
            )
        )
        .scalars()
        .all()
    )

    metadata = (
        await session.execute(
            select(IncomePacketMetadata).where(IncomePacketMetadata.packet_id == packet_id)
        )
    ).scalar_one_or_none()

    finding_rows = (
        (
            await session.execute(
                select(IncomeFinding)
                .where(IncomeFinding.packet_id == packet_id)
                .order_by(IncomeFinding.sort_order)
            )
        )
        .scalars()
        .all()
    )

    # --- Legacy rollup (unchanged) -----------------------------------
    source_outs = [
        IncomeSourceOut(
            id=str(s.id),
            source_code=s.source_code,
            source_name=s.source_name,
            employer=s.employer,
            position=s.position,
            income_type=s.income_type,
            monthly=float(s.monthly_amount),
            annual=float(s.annual_amount),
            trend=s.trend,
            years=float(s.years_history),
            confidence=s.confidence,
            ai_note=s.ai_note,
            mismo=[
                MismoFieldOut(
                    entity=f.get("entity", ""),
                    field=f.get("field", ""),
                    value=f.get("value", ""),
                    confidence=int(f.get("confidence", 0)),
                )
                for f in (s.mismo_fields or [])
            ],
            docs=list(s.docs or []),
        )
        for s in sources
    ]

    dti_outs = [
        DtiItemOut(
            id=str(d.id),
            description=d.description,
            monthly=float(d.monthly_amount),
        )
        for d in dti_items
    ]

    total_monthly = sum((s.monthly_amount for s in sources), Decimal("0"))
    total_annual = sum((s.annual_amount for s in sources), Decimal("0"))
    total_debt = sum((d.monthly_amount for d in dti_items), Decimal("0"))
    dti = (
        (total_debt / total_monthly * Decimal("100")).quantize(Decimal("0.1"))
        if total_monthly > 0
        else Decimal("0.0")
    )

    summary = IncomeSummaryOut(
        total_monthly=float(total_monthly),
        total_annual=float(total_annual),
        total_debt=float(total_debt),
        dti=float(dti),
        source_count=len(sources),
    )

    # --- TI-parity superset ------------------------------------------
    borrowers = _build_borrowers(sources)

    # Housing obligation = first DTI item (PITIA). All DTI items feed
    # the back-end ratio; PITIA alone feeds the front-end.
    pitia = Decimal(dti_items[0].monthly_amount) if dti_items else Decimal("0")
    qualifying_total = sum(
        (
            Decimal(s.total_qualifying)
            if s.total_qualifying is not None
            else Decimal(s.monthly_amount)
            for s in sources
        ),
        Decimal("0"),
    )
    front_end = (
        (pitia / qualifying_total * Decimal("100")).quantize(Decimal("0.1"))
        if qualifying_total > 0
        else Decimal("0.0")
    )
    back_end = (
        (total_debt / qualifying_total * Decimal("100")).quantize(Decimal("0.1"))
        if qualifying_total > 0
        else Decimal("0.0")
    )

    applied_rules_data = (metadata.applied_rules if metadata else {}) or {}
    dti_limit = float(applied_rules_data.get("dti_limit", 45.0))

    applied_rules = AppliedRulesOut(
        program_id=applied_rules_data.get(
            "program_id", packet.declared_program_id or "conventional"
        ),
        dti_limit=dti_limit,
        guidelines=applied_rules_data.get("guidelines", "Fannie Mae Selling Guide"),
        trending_method=applied_rules_data.get("trending_method", "averaged"),
        residual_income_required=bool(applied_rules_data.get("residual_income_required", False)),
    )

    combined = CombinedOut(
        total_monthly_qualifying_income=float(qualifying_total),
        total_monthly_obligations=float(total_debt),
        front_end_dti=float(front_end),
        back_end_dti=float(back_end),
        dti_status=_dti_status(float(back_end), dti_limit),
    )

    residual = None
    if metadata and metadata.residual_income:
        r = metadata.residual_income
        residual = ResidualIncomeOut(
            net_monthly_income=_safe_float(r.get("net_monthly_income")),
            total_obligations=_safe_float(r.get("total_obligations")),
            residual=_safe_float(r.get("residual")),
            regional_table=r.get("regional_table", ""),
            required_residual=_safe_float(r.get("required_residual")),
            meets_requirement=bool(r.get("meets_requirement", False)),
        )

    findings = [
        IncomeFindingOut(
            finding_id=f.finding_id,
            severity=f.severity,
            category=f.category,
            description=f.description,
            recommendation=f.recommendation,
            affected_sources=list(f.affected_sources or []),
            mismo_refs=list(f.mismo_refs or []),
        )
        for f in finding_rows
    ]

    evidence_raw = (metadata.evidence if metadata else []) or []
    evidence = [
        EvidenceTraceOut(
            document_id=e.get("document_id", ""),
            page=int(e.get("page", 0)),
            mismo_path=e.get("mismo_path", ""),
            snippet=e.get("snippet", ""),
        )
        for e in evidence_raw
    ]

    confidence = metadata.confidence if metadata else 0

    return IncomeDashboardOut(
        summary=summary,
        sources=source_outs,
        dti_items=dti_outs,
        packet_id=str(packet_id),
        borrowers=borrowers,
        combined=combined,
        applied_rules=applied_rules,
        residual_income=residual,
        findings=findings,
        evidence=evidence,
        confidence=confidence,
    )
