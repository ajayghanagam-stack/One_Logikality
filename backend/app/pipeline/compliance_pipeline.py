"""Real Compliance pipeline (US-6.3).

After classify + extract, reads Loan Estimate, Closing Disclosure, and
URLA/note document text and asks Claude Sonnet to run TRID/RESPA/ECOA
compliance checks:

  - Disclosure timing (LE/CD delivery within required windows)
  - Fee tolerance comparisons (zero-tolerance, 10%, unlimited buckets)
  - Required disclosures (right-to-cancel, servicing, hazard insurance, etc.)
  - Program-specific overlays
  - Fair lending flags
  - State-specific requirements

Results are persisted as ComplianceCheck, ComplianceFeeTolerance,
ComplianceFinding, and CompliancePacketMetadata rows.

Idempotent: short-circuits when ComplianceCheck rows already exist for the
packet. Returns without writing rows if no disclosure document text is
extractable.
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
    ComplianceCheck,
    ComplianceFeeTolerance,
    ComplianceFinding,
    CompliancePacketMetadata,
    Packet,
)
from app.pipeline.page_utils import load_doc_pages

log = logging.getLogger(__name__)

_COMPLIANCE_DOC_TYPES = [
    "LOAN_ESTIMATE",
    "CLOSING_DISCLOSURE",
    "URLA_1003",
    "PROMISSORY_NOTE",
    "LEAD_PAINT_DISCLOSURE",
    "AFFILIATED_BUSINESS",
    "STATE_DISCLOSURE",
]

_COMPLIANCE_SYSTEM = (
    "You are a TRID/RESPA/ECOA mortgage compliance analyst AI. You receive "
    "the text of disclosure documents from a mortgage packet (Loan Estimate, "
    "Closing Disclosure, loan application, and related disclosures). Evaluate "
    "the packet for regulatory compliance and return structured output.\n\n"
    "COMPLIANCE CHECKS — run each of the following check types:\n"
    "- 'disclosure_timing': Were LE and CD issued within required windows? "
    "(LE: 3 business days of application; CD: 3 business days before closing)\n"
    "- 'fee_tolerance': Do zero-tolerance fees on LE vs CD match? Do "
    "10%-tolerance bucket fees stay within 10%? Do no-tolerance fees differ?\n"
    "- 'required_disclosure': Are required disclosures present and signed? "
    "(Right to Rescind, Servicing Disclosure, HOB, Lead Paint if pre-1978, AfBA)\n"
    "- 'program_specific': Any FHA/VA/USDA/conventional-specific rule violations?\n"
    "- 'fair_lending': ECOA/HMDA: is all required borrower info collected?\n"
    "- 'state_specific': Any obvious state law or regulatory issues?\n\n"
    "For each check:\n"
    "- check_code: short unique identifier (e.g. 'TRID-LE-01', 'RESPA-AfBA-01')\n"
    "- category: human-readable category name\n"
    "- rule: the regulatory rule being checked\n"
    "- status: 'pass', 'fail', 'warn', or 'n/a'\n"
    "- detail: 1-2 sentence finding description\n"
    "- check_type: one of 'disclosure_timing', 'fee_tolerance', "
    "'required_disclosure', 'program_specific', 'fair_lending', 'state_specific'\n"
    "- severity: 'critical', 'warning', or 'info'\n\n"
    "FEE TOLERANCES — produce exactly 3 rows (zero_tolerance, ten_percent, "
    "no_tolerance) comparing LE vs CD fee amounts. If LE/CD are not both "
    "present, use status 'warn' and note the missing document.\n\n"
    "FINDINGS — consolidate the most important compliance issues (max 10).\n\n"
    "OVERALL_CONFIDENCE — 0-100 confidence in the compliance review given "
    "document completeness.\n\n"
    "Return empty arrays if no disclosure documents are provided. "
    "Return only the JSON matching the schema — no prose."
)

_COMPLIANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "check_code": {"type": "string"},
                    "category": {"type": "string"},
                    "rule": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pass", "fail", "warn", "n/a"],
                    },
                    "detail": {"type": "string"},
                    "ai_note": {"type": "string"},
                    "check_type": {
                        "type": "string",
                        "enum": [
                            "disclosure_timing",
                            "fee_tolerance",
                            "required_disclosure",
                            "program_specific",
                            "fair_lending",
                            "state_specific",
                        ],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                    },
                },
                "required": ["check_code", "category", "rule", "status", "detail"],
            },
        },
        "fee_tolerances": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bucket": {"type": "string"},
                    "le_amount": {"type": "string"},
                    "cd_amount": {"type": "string"},
                    "diff_amount": {"type": "string"},
                    "variance_pct": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pass", "fail", "warn"],
                    },
                    "fee_category": {
                        "type": "string",
                        "enum": ["zero_tolerance", "ten_percent", "no_tolerance"],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                    },
                },
                "required": [
                    "bucket",
                    "le_amount",
                    "cd_amount",
                    "diff_amount",
                    "variance_pct",
                    "status",
                ],
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
                        "enum": ["critical", "warning", "info"],
                    },
                    "category": {"type": "string"},
                    "rule_id": {"type": "string"},
                    "description": {"type": "string"},
                    "impact": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "regulatory_citation": {"type": "string"},
                },
                "required": [
                    "finding_id",
                    "severity",
                    "category",
                    "description",
                    "impact",
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
    "required": ["checks", "fee_tolerances", "findings", "overall_confidence"],
}


async def derive_compliance(packet_id: uuid.UUID) -> None:
    """Derive Compliance findings from disclosure document text.

    Idempotent — short-circuits if ComplianceCheck rows already exist.
    Errors are logged and swallowed.
    """
    try:
        await _derive(packet_id)
    except Exception:
        log.exception("compliance_pipeline: unhandled error for packet %s", packet_id)


async def _derive(packet_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(ComplianceCheck.id)
                .where(ComplianceCheck.packet_id == packet_id)
                .limit(1)
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

    pages = await load_doc_pages(packet_id, _COMPLIANCE_DOC_TYPES)
    if not pages:
        log.info("compliance_pipeline: no extractable disclosure text for %s", packet_id)
        return

    lines = [f"Page {n}:\n{text}" for n, text in pages]
    user_content = (
        f"Disclosure documents — {len(pages)} page(s) of extractable text.\n\n"
        + "\n\n---\n\n".join(lines)
    )

    adapter = get_anthropic_adapter()
    response = await adapter.complete(
        model=settings.anthropic_model,
        messages=[
            {"role": "system", "content": _COMPLIANCE_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_schema=_COMPLIANCE_SCHEMA,
    )

    await _persist(packet_id, org_id, response)


async def _persist(
    packet_id: uuid.UUID,
    org_id: uuid.UUID,
    data: dict[str, Any],
) -> None:
    checks = data.get("checks") or []
    fee_tolerances = data.get("fee_tolerances") or []
    findings = data.get("findings") or []
    overall_confidence = int(data.get("overall_confidence") or 0)

    if not checks:
        log.info("compliance_pipeline: Claude returned no checks for packet %s", packet_id)
        return

    check_rows = [
        ComplianceCheck(
            packet_id=packet_id,
            org_id=org_id,
            check_code=c.get("check_code", f"CHK-{i+1:02d}"),
            category=c.get("category", "General"),
            rule=c.get("rule", ""),
            status=c.get("status", "n/a"),
            detail=c.get("detail", ""),
            ai_note=c.get("ai_note") or None,
            mismo_fields=[],
            check_type=c.get("check_type") or None,
            severity=c.get("severity") or None,
            details=None,
        )
        for i, c in enumerate(checks)
    ]

    tolerance_rows = [
        ComplianceFeeTolerance(
            packet_id=packet_id,
            org_id=org_id,
            bucket=t.get("bucket", f"Bucket {i+1}"),
            le_amount=t.get("le_amount", "$0.00"),
            cd_amount=t.get("cd_amount", "$0.00"),
            diff_amount=t.get("diff_amount", "$0.00"),
            variance_pct=t.get("variance_pct", "0%"),
            status=t.get("status", "warn"),
            sort_order=i,
            fee_category=t.get("fee_category") or None,
            severity=t.get("severity") or None,
        )
        for i, t in enumerate(fee_tolerances)
    ]

    finding_rows = [
        ComplianceFinding(
            packet_id=packet_id,
            org_id=org_id,
            finding_id=f.get("finding_id", f"CF-{i+1:02d}"),
            severity=f.get("severity", "info"),
            category=f.get("category", "General"),
            rule_id=f.get("rule_id") or None,
            description=f.get("description", ""),
            impact=f.get("impact", ""),
            recommendation=f.get("recommendation", ""),
            curative=None,
            regulatory_citation=f.get("regulatory_citation") or None,
            affected_parties=[],
            mismo_refs=[],
            sort_order=i,
        )
        for i, f in enumerate(findings)
    ]

    metadata = CompliancePacketMetadata(
        packet_id=packet_id,
        org_id=org_id,
        applied_framework={
            "regulatory": "TRID/RESPA/ECOA",
            "disclosure_set": "standard",
            "program_overlays": [],
        },
        applied_rules={},
        evidence=[],
        confidence=overall_confidence,
    )

    async with SessionLocal() as session:
        session.add_all(check_rows)
        session.add_all(tolerance_rows)
        session.add_all(finding_rows)
        session.add(metadata)
        await session.commit()

    log.info(
        "compliance_pipeline: persisted %d checks, %d tolerances, %d findings for %s",
        len(check_rows),
        len(tolerance_rows),
        len(finding_rows),
        packet_id,
    )
