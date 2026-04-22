"""Real Income Calculation pipeline (US-6.4).

After classify + extract, reads W-2, paystub, tax-return, and VOE document
text and asks Claude Sonnet to:

  - Identify every income source (employer, income type, monthly/annual amount,
    trend, years of history, confidence)
  - Estimate monthly obligations for the DTI calculation
  - Surface income-related findings (missing docs, variances, DTI concerns)

Results are persisted as IncomeSource, IncomeDtiItem, IncomeFinding, and
IncomePacketMetadata rows.

Idempotent: short-circuits when IncomeSource rows already exist for the packet.
Returns empty (no rows written) if no income document text is extractable.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.deps import get_anthropic_adapter
from app.models import (
    IncomeDtiItem,
    IncomeFinding,
    IncomePacketMetadata,
    IncomeSource,
    Packet,
)
from app.pipeline.page_utils import load_doc_pages

log = logging.getLogger(__name__)

_INCOME_DOC_TYPES = [
    "W2_WAGE_STATEMENT",
    "PAYSTUB",
    "TAX_RETURN_1040",
    "TAX_SCHEDULE_E",
    "VOE",
    "IRS_4506T",
]

_INCOME_SYSTEM = (
    "You are a mortgage income analyst AI. You receive the full text of "
    "income-related documents from a mortgage packet (W-2s, pay stubs, "
    "federal tax returns, schedules, and verifications of employment). "
    "Analyse the documents and return structured income calculation data.\n\n"
    "INCOME SOURCES — identify each distinct income stream. For each:\n"
    "- source_code: short unique identifier (e.g. 'W2-01', 'SELF-01', 'RENT-01')\n"
    "- source_name: human-readable label (e.g. 'W-2 Base Salary — Acme Corp')\n"
    "- employer: employer/payer name from the document (or null)\n"
    "- position: job title / position (or null if not stated)\n"
    "- income_type: one of 'base', 'overtime', 'bonus', 'commission', "
    "'rental', 'social_security', 'pension', 'other'\n"
    "- monthly_amount: calculated monthly gross amount (number)\n"
    "- annual_amount: annual gross amount (number)\n"
    "- trend: 'stable', 'increasing', or 'decreasing'\n"
    "- years_history: documented years of income history (number)\n"
    "- confidence: 0-100 (how confidently you read the values)\n"
    "- category: 'employment' or 'non_employment'\n"
    "- employment_type: 'w2', 'self_employed', '1099', or 'military' (null for non-employment)\n"
    "- docs: list of document types this source is derived from\n\n"
    "DTI OBLIGATIONS — identify every monthly obligation (PITIA estimate if "
    "loan terms are visible, plus all recurring debts listed on the application "
    "or credit report text). Each has a description and monthly_amount (number).\n\n"
    "FINDINGS — flag any income issues: missing W-2 years, income variances "
    "between documents, declining trends, DTI concerns, incomplete verification. "
    "Each finding: finding_id (e.g. 'F-01'), severity ('critical', 'review', or "
    "'info'), category ('missing_doc', 'variance', 'trending_concern', "
    "'dti_exceeded', or 'incomplete_verification'), description, recommendation.\n\n"
    "OVERALL_CONFIDENCE — your overall confidence (0-100) in the income "
    "calculation given the document quality and completeness.\n\n"
    "Return empty arrays if no income documents are provided or text is blank. "
    "Return only the JSON matching the schema — no prose."
)

_INCOME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "income_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_code": {"type": "string"},
                    "source_name": {"type": "string"},
                    "employer": {"type": "string"},
                    "position": {"type": "string"},
                    "income_type": {"type": "string"},
                    "monthly_amount": {"type": "number"},
                    "annual_amount": {"type": "number"},
                    "trend": {
                        "type": "string",
                        "enum": ["stable", "increasing", "decreasing"],
                    },
                    "years_history": {"type": "number"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "category": {
                        "type": "string",
                        "enum": ["employment", "non_employment"],
                    },
                    "employment_type": {
                        "type": "string",
                        "enum": ["w2", "self_employed", "1099", "military"],
                    },
                    "docs": {"type": "array", "items": {"type": "string"}},
                    "ai_note": {"type": "string"},
                },
                "required": [
                    "source_code",
                    "source_name",
                    "income_type",
                    "monthly_amount",
                    "annual_amount",
                    "trend",
                    "years_history",
                    "confidence",
                    "category",
                ],
            },
        },
        "dti_obligations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "monthly_amount": {"type": "number"},
                },
                "required": ["description", "monthly_amount"],
            },
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "review", "info"],
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "missing_doc",
                            "variance",
                            "trending_concern",
                            "dti_exceeded",
                            "incomplete_verification",
                        ],
                    },
                    "description": {"type": "string"},
                    "recommendation": {"type": "string"},
                },
                "required": [
                    "finding_id",
                    "severity",
                    "category",
                    "description",
                    "recommendation",
                ],
            },
        },
        "overall_confidence": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
        },
    },
    "required": ["income_sources", "dti_obligations", "findings", "overall_confidence"],
}


async def derive_income(packet_id: uuid.UUID) -> None:
    """Derive Income Calculation findings from income document text.

    Idempotent — short-circuits if IncomeSource rows already exist.
    Errors are logged and swallowed.
    """
    try:
        await _derive(packet_id)
    except Exception:
        log.exception("income_pipeline: unhandled error for packet %s", packet_id)


async def _derive(packet_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(IncomeSource.id).where(IncomeSource.packet_id == packet_id).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        packet_org = (
            await session.execute(select(Packet.org_id).where(Packet.id == packet_id))
        ).scalar_one_or_none()
        if packet_org is None:
            return
    org_id = packet_org

    pages = await load_doc_pages(packet_id, _INCOME_DOC_TYPES)
    if not pages:
        log.info("income_pipeline: no extractable income doc text for %s", packet_id)
        return

    lines = [f"Page {n}:\n{text}" for n, text in pages]
    user_content = (
        f"Income documents — {len(pages)} page(s) of extractable text.\n\n"
        + "\n\n---\n\n".join(lines)
    )

    adapter = get_anthropic_adapter()
    response = await adapter.complete(
        model=settings.anthropic_model,
        messages=[
            {"role": "system", "content": _INCOME_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_schema=_INCOME_SCHEMA,
    )

    await _persist(packet_id, org_id, response)


async def _persist(
    packet_id: uuid.UUID,
    org_id: uuid.UUID,
    data: dict[str, Any],
) -> None:
    income_sources = data.get("income_sources") or []
    dti_obligations = data.get("dti_obligations") or []
    findings = data.get("findings") or []
    overall_confidence = int(data.get("overall_confidence") or 0)

    if not income_sources:
        log.info("income_pipeline: Claude returned no income sources for packet %s", packet_id)
        return

    source_rows = [
        IncomeSource(
            packet_id=packet_id,
            org_id=org_id,
            source_code=src.get("source_code", f"SRC-{i+1:02d}"),
            source_name=src.get("source_name", ""),
            employer=src.get("employer") or None,
            position=src.get("position") or None,
            income_type=src.get("income_type", "base"),
            monthly_amount=float(src.get("monthly_amount", 0)),
            annual_amount=float(src.get("annual_amount", 0)),
            trend=src.get("trend", "stable"),
            years_history=float(src.get("years_history", 0)),
            confidence=int(src.get("confidence", 0)),
            ai_note=src.get("ai_note") or None,
            mismo_fields=[],
            docs=list(src.get("docs") or []),
            sort_order=i,
            category=src.get("category", "employment"),
            employment_type=src.get("employment_type") or None,
        )
        for i, src in enumerate(income_sources)
    ]

    dti_rows = [
        IncomeDtiItem(
            packet_id=packet_id,
            org_id=org_id,
            description=row.get("description", ""),
            monthly_amount=float(row.get("monthly_amount", 0)),
            sort_order=i,
        )
        for i, row in enumerate(dti_obligations)
    ]

    finding_rows = [
        IncomeFinding(
            packet_id=packet_id,
            org_id=org_id,
            finding_id=f.get("finding_id", f"F-{i+1:02d}"),
            severity=f.get("severity", "info"),
            category=f.get("category", "incomplete_verification"),
            description=f.get("description", ""),
            recommendation=f.get("recommendation", ""),
            affected_sources=[],
            mismo_refs=[],
            sort_order=i,
        )
        for i, f in enumerate(findings)
    ]

    metadata = IncomePacketMetadata(
        packet_id=packet_id,
        org_id=org_id,
        applied_rules={},
        residual_income=None,
        evidence=[],
        confidence=overall_confidence,
    )

    async with SessionLocal() as session:
        session.add_all(source_rows)
        session.add_all(dti_rows)
        session.add_all(finding_rows)
        session.add(metadata)
        await session.commit()

    log.info(
        "income_pipeline: persisted %d sources, %d DTI items, %d findings for %s",
        len(source_rows),
        len(dti_rows),
        len(finding_rows),
        packet_id,
    )
