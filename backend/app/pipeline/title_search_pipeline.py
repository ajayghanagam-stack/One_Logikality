"""Real Title Search & Abstraction pipeline (US-6.1).

After classify + extract, reads the text of TITLE_COMMITMENT, WARRANTY_DEED,
and DEED_OF_TRUST documents and asks Claude Sonnet to:

  - Identify property details (address, legal description, APN, vesting)
  - Surface chain-of-title issues, unreleased liens, easements,
    name discrepancies, tax delinquencies, and other risk flags
  - Produce an AI recommendation (approve/reject/escalate) for each flag
  - Build a structured property summary (chain of title, mortgages, liens,
    easements, taxes, title insurance details)

Results are persisted as TitleFlag and TitleProperty rows.

Idempotent: short-circuits when TitleFlag rows already exist for the packet.
Returns without writing rows if no title document text is extractable.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.deps import get_anthropic_adapter
from app.models import Packet, TitleFlag, TitleProperty
from app.pipeline.page_utils import load_doc_pages

log = logging.getLogger(__name__)

_TITLE_SEARCH_DOC_TYPES = [
    "TITLE_COMMITMENT",
    "WARRANTY_DEED",
    "DEED_OF_TRUST",
]

_TITLE_SEARCH_SYSTEM = (
    "You are a real-estate title abstractor AI. You receive the text of "
    "title-related documents from a mortgage packet (title commitment, "
    "warranty deed, deed of trust). Analyse them and return structured "
    "title search output.\n\n"
    "FLAGS — identify every risk item that requires examiner attention:\n"
    "- flag_type: short category code from the enum\n"
    "- title: 6-10 word description\n"
    "- description: 2-4 sentences explaining the issue and its significance\n"
    "- severity: 'critical' (blocks closing), 'high' (requires curative "
    "action), 'medium' (monitor), or 'low' (informational)\n"
    "- page_ref: page reference string (e.g. 'Pg. 3' or 'Sch. B-1')\n"
    "- ai_note: 1-2 sentence AI examiner note\n"
    "- ai_rec_decision: 'approve', 'reject', or 'escalate'\n"
    "- ai_rec_confidence: 0-100 confidence in the decision\n"
    "- ai_rec_reasoning: 1-2 sentences explaining the recommendation\n\n"
    "FLAG TYPES (use one of these):\n"
    "unreleased_lien, chain_of_title_gap, easement, name_discrepancy, "
    "missing_endorsement, tax_delinquency, vesting_issue, deed_defect, "
    "boundary_issue, covenants_restrictions, missing_release, other\n\n"
    "PROPERTY SUMMARY — a single structured summary with these fields:\n"
    "- property_id: short identifier\n"
    "- address: full street address\n"
    "- legal_description: legal description from the deed/commitment\n"
    "- apn: assessor parcel number (or null)\n"
    "- property_type: 'SFR', 'Condo', 'Multi-Family', 'Commercial', etc.\n"
    "- vesting: how title is vested (names and tenancy)\n"
    "- chain_of_title: array of prior conveyances (each with grantor, "
    "grantee, date, instrument_no)\n"
    "- mortgages: array of current mortgage liens (each with lender, "
    "amount, date, instrument_no, status)\n"
    "- liens: array of other liens (each with lienholder, amount, "
    "type, date, status)\n"
    "- easements: array of easements (each with type, description, "
    "grantor, status)\n"
    "- taxes: object with year, amount, status ('current', 'delinquent', "
    "or 'unknown'), and next_due date\n"
    "- title_insurance: object with company, effective_date, "
    "commitment_number, amount\n\n"
    "Return empty arrays/null if document text is blank. "
    "Return only the JSON matching the schema — no prose."
)

_TITLE_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "flag_type": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "page_ref": {"type": "string"},
                    "ai_note": {"type": "string"},
                    "ai_rec_decision": {
                        "type": "string",
                        "enum": ["approve", "reject", "escalate"],
                    },
                    "ai_rec_confidence": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "ai_rec_reasoning": {"type": "string"},
                },
                "required": ["flag_type", "title", "description", "severity", "page_ref"],
            },
        },
        "property_summary": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "address": {"type": "string"},
                "legal_description": {"type": "string"},
                "apn": {"type": "string"},
                "property_type": {"type": "string"},
                "vesting": {"type": "string"},
                "chain_of_title": {"type": "array", "items": {"type": "object"}},
                "mortgages": {"type": "array", "items": {"type": "object"}},
                "liens": {"type": "array", "items": {"type": "object"}},
                "easements": {"type": "array", "items": {"type": "object"}},
                "taxes": {"type": "object"},
                "title_insurance": {"type": "object"},
            },
        },
    },
    "required": ["flags", "property_summary"],
}


async def derive_title_search(packet_id: uuid.UUID) -> None:
    """Derive Title Search findings from title document text.

    Idempotent — short-circuits if TitleFlag rows already exist.
    Errors are logged and swallowed.
    """
    try:
        await _derive(packet_id)
    except Exception:
        log.exception("title_search_pipeline: unhandled error for packet %s", packet_id)


async def _derive(packet_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(TitleFlag.id).where(TitleFlag.packet_id == packet_id).limit(1)
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

    pages = await load_doc_pages(packet_id, _TITLE_SEARCH_DOC_TYPES)
    if not pages:
        log.info("title_search_pipeline: no extractable title doc text for %s", packet_id)
        return

    lines = [f"Page {n}:\n{text}" for n, text in pages]
    user_content = (
        f"Title documents — {len(pages)} page(s) of extractable text.\n\n"
        + "\n\n---\n\n".join(lines)
    )

    adapter = get_anthropic_adapter()
    response = await adapter.complete(
        model=settings.anthropic_model,
        messages=[
            {"role": "system", "content": _TITLE_SEARCH_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_schema=_TITLE_SEARCH_SCHEMA,
    )

    await _persist(packet_id, org_id, response)


async def _persist(
    packet_id: uuid.UUID,
    org_id: uuid.UUID,
    data: dict[str, Any],
) -> None:
    flags = data.get("flags") or []
    property_summary = data.get("property_summary") or {}

    flag_rows = [
        TitleFlag(
            packet_id=packet_id,
            org_id=org_id,
            flag_number=i + 1,
            severity=f.get("severity", "medium"),
            flag_type=f.get("flag_type", "other"),
            title=f.get("title", ""),
            description=f.get("description", ""),
            page_ref=f.get("page_ref", ""),
            ai_note=f.get("ai_note") or None,
            ai_rec_decision=f.get("ai_rec_decision") or None,
            ai_rec_confidence=f.get("ai_rec_confidence") or None,
            ai_rec_reasoning=f.get("ai_rec_reasoning") or None,
            mismo_fields=[],
            source={"doc_type": "TITLE_COMMITMENT", "pages": []},
            cross_app=None,
            evidence=[],
            sort_order=i,
        )
        for i, f in enumerate(flags)
    ]

    rows: list[Any] = list(flag_rows)
    if property_summary:
        rows.append(
            TitleProperty(
                packet_id=packet_id,
                org_id=org_id,
                summary=property_summary,
            )
        )

    if not rows:
        log.info("title_search_pipeline: Claude returned no data for packet %s", packet_id)
        return

    async with SessionLocal() as session:
        session.add_all(rows)
        await session.commit()

    log.info(
        "title_search_pipeline: persisted %d flags + property summary for %s",
        len(flag_rows),
        packet_id,
    )
