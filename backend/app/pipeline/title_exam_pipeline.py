"""Real Title Examination pipeline (US-6.2).

After classify + extract have run, reads the raw page text from every
TITLE_COMMITMENT document and asks Claude Sonnet to identify:

  - Schedule B standard exceptions (boilerplate ALTA / T-7 pre-printed items)
  - Schedule B specific exceptions (property-specific risks with severity)
  - Schedule C requirements (conditions to be satisfied before policy issuance)
  - Examiner warnings (red-flag observations outside B/C categories)
  - Curative checklist (action items generated from Schedule C + warnings)

Results are persisted as TitleExamException, TitleExamRequirement,
TitleExamWarning, and TitleExamChecklistItem rows.

Idempotent: short-circuits when TitleExamException rows already exist for
the packet (same guard as validate.py / ecv sections).

If no TITLE_COMMITMENT pages have extractable text (e.g. fully scanned PDF)
the function logs a warning and returns without writing any rows — the
frontend renders an empty state.
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
    Packet,
    TitleExamChecklistItem,
    TitleExamException,
    TitleExamRequirement,
    TitleExamWarning,
)
from app.pipeline.page_utils import load_doc_pages

log = logging.getLogger(__name__)

_TITLE_EXAM_SYSTEM = (
    "You are a real-estate title examiner AI. You receive the full text of "
    "one or more Title Commitment documents (ALTA form T-7 or state equivalent). "
    "Analyse the document and return a structured title examination output.\n\n"
    "SCHEDULE B STANDARD EXCEPTIONS — boilerplate items pre-printed in every "
    "title commitment (e.g. taxes not yet due, easements of record, rights of "
    "parties in possession, survey discrepancies). Set severity to 'low' unless "
    "the item reveals a specific unresolved risk. The flag_type field is optional "
    "— omit it for generic boilerplate items.\n\n"
    "SCHEDULE B SPECIFIC EXCEPTIONS — property-specific items added by the "
    "underwriter (unreleased liens, deed restrictions, recorded covenants, "
    "easements by instrument, etc.). Assess severity as 'critical' (blocks "
    "closing), 'high' (requires curative action), 'medium' (monitor), or "
    "'low' (informational). Set flag_type to the most applicable risk category "
    "from the enum provided.\n\n"
    "SCHEDULE C REQUIREMENTS — conditions the buyer/seller/lender must satisfy "
    "before the title policy will issue. Assign priority as 'must_close' "
    "(blocking — closing cannot proceed without it), 'should_close' "
    "(important but may survive to post-closing with escrow), or 'recommended'. "
    "Set status to 'open' unless the document clearly shows the condition was "
    "already satisfied.\n\n"
    "WARNINGS — material observations that don't fit Schedule B/C but represent "
    "risk or require examiner attention (e.g. missing endorsements, potential "
    "chain-of-title issues not yet expressed as a specific exception).\n\n"
    "CHECKLIST ITEMS — actionable curative steps derived directly from the "
    "Schedule C requirements and warnings. Number them starting at 1. Each has "
    "an action description, a priority, and starts unchecked.\n\n"
    "If the provided document text is blank or contains no recognisable title "
    "commitment content, return empty arrays for ALL fields — do NOT invent "
    "fictitious exceptions.\n\n"
    "Return only the JSON matching the schema — no prose."
)

_FLAG_TYPE_ENUM = [
    "missing_endorsement",
    "unacceptable_exception",
    "unresolved_lien",
    "unreleased_mortgage",
    "cross_section_mismatch",
    "requirement_missing_proof",
    "name_discrepancy",
    "marital_status_issue",
    "incomplete_document",
    "regulatory_compliance",
    "chain_of_title_gap",
    "document_defect",
    "mineral_rights",
    "trust_issue",
    "estate_issue",
    "vesting_issue",
    "tax_issue",
]

_EXCEPTION_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "number": {"type": "integer"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
        "page_ref": {"type": "string"},
        "ai_explanation": {"type": "string"},
        "flag_type": {"type": "string", "enum": _FLAG_TYPE_ENUM},
    },
    "required": ["number", "title", "description", "severity"],
}

_TITLE_EXAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "standard_exceptions": {"type": "array", "items": _EXCEPTION_ITEM},
        "specific_exceptions": {"type": "array", "items": _EXCEPTION_ITEM},
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["must_close", "should_close", "recommended"],
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "requested", "provided", "not_ordered"],
                    },
                    "page_ref": {"type": "string"},
                    "ai_explanation": {"type": "string"},
                },
                "required": ["number", "title", "description", "priority", "status"],
            },
        },
        "warnings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "flag_type": {"type": "string", "enum": _FLAG_TYPE_ENUM},
                    "ai_explanation": {"type": "string"},
                },
                "required": ["title", "description", "severity"],
            },
        },
        "checklist_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "action": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["must_close", "should_close", "recommended"],
                    },
                    "note": {"type": "string"},
                },
                "required": ["number", "action", "priority"],
            },
        },
    },
    "required": [
        "standard_exceptions",
        "specific_exceptions",
        "requirements",
        "warnings",
        "checklist_items",
    ],
}


async def derive_title_exam(packet_id: uuid.UUID) -> None:
    """Derive Title Examination findings from TITLE_COMMITMENT document text.

    Idempotent — short-circuits if TitleExamException rows already exist for
    this packet. Failures are logged and swallowed so the pipeline stage
    completes even when Claude is unreachable.
    """
    try:
        await _derive(packet_id)
    except Exception:
        log.exception("title_exam_pipeline: unhandled error for packet %s", packet_id)


async def _derive(packet_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(TitleExamException.id)
                .where(TitleExamException.packet_id == packet_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            log.debug("title_exam_pipeline: findings already exist for %s, skipping", packet_id)
            return

        packet_org = (
            await session.execute(select(Packet.org_id).where(Packet.id == packet_id))
        ).scalar_one_or_none()
        if packet_org is None:
            log.warning("title_exam_pipeline: packet %s vanished", packet_id)
            return
    org_id = packet_org

    pages = await load_doc_pages(packet_id, ["TITLE_COMMITMENT"])
    if not pages:
        log.info(
            "title_exam_pipeline: no extractable TITLE_COMMITMENT text for %s", packet_id
        )
        return

    lines = [f"Page {n}:\n{text}" for n, text in pages]
    user_content = (
        f"Title Commitment documents — {len(pages)} page(s) of extractable text.\n\n"
        + "\n\n---\n\n".join(lines)
    )

    adapter = get_anthropic_adapter()
    response = await adapter.complete(
        model=settings.anthropic_model,
        messages=[
            {"role": "system", "content": _TITLE_EXAM_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_schema=_TITLE_EXAM_SCHEMA,
    )

    await _persist(packet_id, org_id, response)


async def _persist(
    packet_id: uuid.UUID,
    org_id: uuid.UUID,
    data: dict[str, Any],
) -> None:
    std_exceptions = data.get("standard_exceptions") or []
    spec_exceptions = data.get("specific_exceptions") or []
    requirements = data.get("requirements") or []
    warnings = data.get("warnings") or []
    checklist_items = data.get("checklist_items") or []

    if not (std_exceptions or spec_exceptions or requirements or warnings):
        log.info(
            "title_exam_pipeline: Claude returned no findings for packet %s", packet_id
        )
        return

    exception_rows: list[TitleExamException] = []
    for i, exc in enumerate(std_exceptions):
        exception_rows.append(
            TitleExamException(
                packet_id=packet_id,
                org_id=org_id,
                schedule="standard",
                exception_number=int(exc.get("number", i + 1)),
                severity=exc.get("severity", "low"),
                title=exc.get("title", ""),
                description=exc.get("description", ""),
                page_ref=exc.get("page_ref") or None,
                note=None,
                flag_type=exc.get("flag_type") or None,
                ai_explanation=exc.get("ai_explanation") or None,
                evidence_refs=[],
                sort_order=i,
            )
        )
    offset = len(std_exceptions)
    for i, exc in enumerate(spec_exceptions):
        exception_rows.append(
            TitleExamException(
                packet_id=packet_id,
                org_id=org_id,
                schedule="specific",
                exception_number=int(exc.get("number", i + 1)),
                severity=exc.get("severity", "medium"),
                title=exc.get("title", ""),
                description=exc.get("description", ""),
                page_ref=exc.get("page_ref") or None,
                note=None,
                flag_type=exc.get("flag_type") or None,
                ai_explanation=exc.get("ai_explanation") or None,
                evidence_refs=[],
                sort_order=offset + i,
            )
        )

    requirement_rows = [
        TitleExamRequirement(
            packet_id=packet_id,
            org_id=org_id,
            requirement_number=int(r.get("number", i + 1)),
            title=r.get("title", ""),
            priority=r.get("priority", "should_close"),
            status=r.get("status", "open"),
            page_ref=r.get("page_ref") or None,
            description=r.get("description", ""),
            note=None,
            ai_explanation=r.get("ai_explanation") or None,
            evidence_refs=[],
            sort_order=i,
        )
        for i, r in enumerate(requirements)
    ]

    warning_rows = [
        TitleExamWarning(
            packet_id=packet_id,
            org_id=org_id,
            severity=w.get("severity", "medium"),
            title=w.get("title", ""),
            description=w.get("description", ""),
            note=None,
            flag_type=w.get("flag_type") or None,
            ai_explanation=w.get("ai_explanation") or None,
            evidence_refs=[],
            sort_order=i,
        )
        for i, w in enumerate(warnings)
    ]

    checklist_rows = [
        TitleExamChecklistItem(
            packet_id=packet_id,
            org_id=org_id,
            item_number=int(c.get("number", i + 1)),
            action=c.get("action", ""),
            priority=c.get("priority", "should_close"),
            checked=False,
            note=c.get("note") or None,
            sort_order=i,
        )
        for i, c in enumerate(checklist_items)
    ]

    async with SessionLocal() as session:
        session.add_all(exception_rows)
        session.add_all(requirement_rows)
        session.add_all(warning_rows)
        session.add_all(checklist_rows)
        await session.commit()

    log.info(
        "title_exam_pipeline: persisted %d exceptions, %d requirements, "
        "%d warnings, %d checklist items for packet %s",
        len(exception_rows),
        len(requirement_rows),
        len(warning_rows),
        len(checklist_rows),
        packet_id,
    )
