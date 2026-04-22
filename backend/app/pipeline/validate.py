"""Real per-packet validation + scoring — the `validate` / `score` stages.

For each of 13 industry-standard ECV sections, ask Claude Sonnet 4 to
evaluate that section's 3-5 line-item checks against the packet's MISMO
3.6 extractions (produced by M3) and the document inventory (produced by
M2). Claude returns a per-check `result` string + `confidence` (0-100);
the section score rolls up as the mean confidence of its line items.

M4 scope:
- The 58 check definitions are static and industry-standard; only the
  per-check `result` / `confidence` are AI-generated. Keeping the check
  set deterministic means the dashboard always renders the same shape
  across packets and the checks themselves are auditable / editable
  without a model round-trip.
- One Claude call per section (13 calls total) — simpler than batching
  all 58 checks into a single mega-call and keeps failures isolated to
  one section when they happen. Failures are logged and the affected
  section falls back to confidence=0 / result="validation failed".
- Tests monkeypatch `validate_packet` to avoid calling Anthropic; see
  `tests/conftest.py::_stub_validate`, which seeds canned rows so the
  dashboard endpoint keeps returning its expected shape.

RLS: writes bypass RLS by running as postgres superuser — same design
as the classify/extract stages; server-internal orchestration.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, NotRequired, TypedDict

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.deps import get_anthropic_adapter
from app.models import EcvDocument, EcvExtraction, EcvLineItem, EcvSection, Packet

log = logging.getLogger(__name__)


class _SectionDef(TypedDict):
    number: int
    name: str
    weight: int


class _CheckDef(TypedDict):
    id: str
    check: str
    # Which downstream micro-apps this check feeds. Omitted (or ()) means
    # "core ECV check — applies to every packet regardless of scope". When
    # present, the dashboard treats the check as out-of-scope for any
    # packet whose `scoped_app_ids` doesn't intersect these ids.
    app_ids: NotRequired[tuple[str, ...]]


# 13 sections with weights summing to 100 (matches industry-standard
# ECV weighting). Section 13 (cross-doc reconciliation) has weight 0 —
# it contributes to the line-item confidence stats but not the
# weighted-score rollup.
_SECTION_DEFS: tuple[_SectionDef, ...] = (
    {"number": 1, "name": "Document completeness", "weight": 8},
    {"number": 2, "name": "Borrower identity", "weight": 12},
    {"number": 3, "name": "Property consistency", "weight": 10},
    {"number": 4, "name": "Loan terms", "weight": 15},
    {"number": 5, "name": "Financial / underwriting", "weight": 15},
    {"number": 6, "name": "Appraisal", "weight": 10},
    {"number": 7, "name": "Title & legal", "weight": 8},
    {"number": 8, "name": "Regulatory compliance", "weight": 10},
    {"number": 9, "name": "Signatures & dates", "weight": 5},
    {"number": 10, "name": "Insurance", "weight": 3},
    {"number": 11, "name": "Document quality", "weight": 2},
    {"number": 12, "name": "Condition clearance", "weight": 2},
    {"number": 13, "name": "Cross-doc reconciliation", "weight": 0},
)


# 58 line-item check definitions grouped by section. These are the
# industry-standard mortgage validation questions — auditable, durable,
# and **not** AI-generated. Claude's job is to answer them given the
# packet's extractions, not to invent the questions.
_CHECK_DEFS: dict[int, tuple[_CheckDef, ...]] = {
    1: (
        {"id": "1.1", "check": "All 25 required documents present"},
        {"id": "1.2", "check": "No missing pages within documents"},
        {"id": "1.3", "check": "Required addenda & riders attached"},
        {"id": "1.4", "check": "All signature pages included"},
    ),
    2: (
        {"id": "2.1", "check": "Borrower name matches across all docs"},
        {"id": "2.2", "check": "SSN matches on application, credit, tax, 4506-T"},
        {"id": "2.3", "check": "DOB consistent across documents"},
        {"id": "2.4", "check": "Marital status consistent"},
        {"id": "2.5", "check": "Address history matches"},
    ),
    3: (
        {"id": "3.1", "check": "Property address matches on every document"},
        {"id": "3.2", "check": "Legal description matches deed, title, appraisal"},
        {"id": "3.3", "check": "Parcel/APN number consistent"},
        {"id": "3.4", "check": "Property type consistent (SFR/Condo/Multi)"},
    ),
    4: (
        {"id": "4.1", "check": "Loan amount matches across LE, CD, Note, Deed"},
        {"id": "4.2", "check": "Interest rate consistent"},
        {"id": "4.3", "check": "Loan term matches"},
        {"id": "4.4", "check": "Monthly P&I calculates correctly"},
        {"id": "4.5", "check": "Escrow amounts for tax/insurance match"},
    ),
    5: (
        {
            "id": "5.1",
            "check": "W-2 income reconciles with application",
            "app_ids": ("income-calc",),
        },
        {"id": "5.2", "check": "DTI ratio within guidelines", "app_ids": ("income-calc",)},
        {
            "id": "5.3",
            "check": "Bank statements support down payment & reserves",
            "app_ids": ("income-calc",),
        },
        {"id": "5.4", "check": "Gift letter properly executed", "app_ids": ("income-calc",)},
        {
            "id": "5.5",
            "check": "Employment VOE matches application",
            "app_ids": ("income-calc",),
        },
    ),
    6: (
        {"id": "6.1", "check": "Appraised value supports LTV ratio"},
        {"id": "6.2", "check": "Appraisal dated within acceptable window"},
        {"id": "6.3", "check": "Comparable sales appropriate"},
        {"id": "6.4", "check": "Appraiser licensed for state"},
    ),
    7: (
        {
            "id": "7.1",
            "check": "Title clear of unexpected liens",
            "app_ids": ("title-search", "title-exam"),
        },
        {
            "id": "7.2",
            "check": "Prior mortgages satisfied",
            "app_ids": ("title-search", "title-exam"),
        },
        {"id": "7.3", "check": "Vesting correct", "app_ids": ("title-search", "title-exam")},
        {
            "id": "7.4",
            "check": "Title commitment matches final policy",
            "app_ids": ("title-search", "title-exam"),
        },
    ),
    8: (
        {
            "id": "8.1",
            "check": "Loan Estimate delivered within 3 business days",
            "app_ids": ("compliance",),
        },
        {
            "id": "8.2",
            "check": "Closing Disclosure delivered 3 days before closing",
            "app_ids": ("compliance",),
        },
        {
            "id": "8.3",
            "check": "Fee tolerance checks (0%, 10%, unlimited)",
            "app_ids": ("compliance",),
        },
        {
            "id": "8.4",
            "check": "State-specific disclosures present",
            "app_ids": ("compliance",),
        },
    ),
    9: (
        {"id": "9.1", "check": "All parties signed required documents"},
        {"id": "9.2", "check": "Signatures consistent across documents"},
        {"id": "9.3", "check": "Dates logical and chronological"},
        {"id": "9.4", "check": "Notarization valid (seal, commission, state)"},
    ),
    10: (
        {"id": "10.1", "check": "Hazard insurance in force"},
        {"id": "10.2", "check": "Lender listed as mortgagee"},
        {"id": "10.3", "check": "Flood insurance (if required)"},
        {"id": "10.4", "check": "PMI disclosed and in place"},
    ),
    11: (
        {"id": "11.1", "check": "All pages legible"},
        {"id": "11.2", "check": "No signs of alteration or tampering"},
        {"id": "11.3", "check": "Correct orientation on all pages"},
        {"id": "11.4", "check": "No DRAFT watermarks on final docs"},
    ),
    12: (
        {"id": "12.1", "check": "Prior-to-doc conditions satisfied"},
        {"id": "12.2", "check": "Prior-to-funding conditions satisfied"},
        {"id": "12.3", "check": "All conditions documented with evidence"},
    ),
    13: (
        {"id": "13.1", "check": "CD closing costs match settlement statement"},
        {"id": "13.2", "check": "Prorated taxes calculate correctly"},
        {"id": "13.3", "check": "Cash-to-close reconciles"},
        {"id": "13.4", "check": "Prepaid interest calculates correctly"},
    ),
}


_VALIDATE_SYSTEM = (
    "You are a mortgage-loan validation reviewer. You receive (a) a list "
    "of MISMO 3.6 field extractions from a mortgage packet plus a summary "
    "of the packet's document inventory, and (b) a list of checks for one "
    "validation section. Evaluate each check against the extracted data "
    "and return a short human-readable `result` string plus a confidence "
    "score (0-100).\n\n"
    "Confidence rubric:\n"
    "- 90-100: the evidence clearly supports a pass (values match, dates "
    "consistent, documents present).\n"
    "- 50-89: partial / ambiguous evidence — one doc supports it but "
    "another is inconsistent or missing.\n"
    "- 0-49: the evidence contradicts the check OR required data is "
    "entirely missing so no real judgement is possible.\n\n"
    "For `result`, be terse — 3-10 words — and cite a concrete value where "
    "you have one (e.g. '$400,000 — match across 4 docs', 'Mismatch: "
    "$400,000 vs $405,000', 'Missing W-2'). If the check doesn't apply "
    "(e.g. gift letter on a packet with no gift funds), result='N/A' with "
    "confidence=100.\n\n"
    "Return exactly one entry per check id; do not invent checks. Return "
    "only the JSON matching the schema."
)

_VALIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "result": {"type": "string"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["id", "result", "confidence"],
            },
        }
    },
    "required": ["line_items"],
}


async def validate_packet(packet_id: uuid.UUID) -> None:
    """Validate a packet's extractions against the 13-section check set.

    Persists `EcvSection` (with score = mean of member line-item
    confidences) and `EcvLineItem` rows. If sections already exist for
    the packet (e.g. a replay) we short-circuit — the stage is not
    idempotent by itself; callers gate on existence.
    """
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(EcvSection.id).where(EcvSection.packet_id == packet_id).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        packet_org = (
            await session.execute(select(Packet.org_id).where(Packet.id == packet_id))
        ).scalar_one_or_none()
        if packet_org is None:
            log.warning("validate: packet %s vanished before validation", packet_id)
            return

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

    context = _format_context(extractions=list(extractions), documents=list(documents))
    adapter = get_anthropic_adapter()

    section_rows: list[EcvSection] = []
    line_item_rows: list[EcvLineItem] = []

    for section_def in _SECTION_DEFS:
        checks = _CHECK_DEFS[section_def["number"]]
        try:
            graded = await _validate_section(
                adapter=adapter,
                section_name=section_def["name"],
                checks=checks,
                context=context,
            )
        except Exception:
            log.exception(
                "validate: section %s Claude call failed; marking section zero",
                section_def["number"],
            )
            graded = {c["id"]: {"result": "validation failed", "confidence": 0} for c in checks}

        section_confidences: list[int] = []
        section = EcvSection(
            packet_id=packet_id,
            org_id=packet_org,
            section_number=section_def["number"],
            name=section_def["name"],
            weight=section_def["weight"],
            score=0,  # backfilled after line items tallied
        )
        section_rows.append(section)

        for check in checks:
            graded_row = graded.get(
                check["id"],
                {"result": "no response", "confidence": 0},
            )
            confidence = int(graded_row["confidence"])
            confidence = max(0, min(100, confidence))
            section_confidences.append(confidence)
            check_app_ids = check.get("app_ids") or ()
            line_item_rows.append(
                EcvLineItem(
                    section_id=None,  # populated after section flush gives us IDs
                    packet_id=packet_id,
                    org_id=packet_org,
                    item_code=check["id"],
                    check_description=check["check"],
                    result_text=str(graded_row.get("result", ""))[:500],
                    confidence=confidence,
                    # Empty tuple ⇒ NULL so the DB distinguishes "core check"
                    # (never out-of-scope) from "scoped but empty list" (never
                    # written today but reserved for future semantics).
                    app_ids=list(check_app_ids) if check_app_ids else None,
                )
            )

        section.score = (
            round(sum(section_confidences) / len(section_confidences)) if section_confidences else 0
        )

    async with SessionLocal() as session:
        session.add_all(section_rows)
        await session.flush()
        section_id_by_number = {s.section_number: s.id for s in section_rows}
        # Line items don't carry section_number directly — they were
        # built in the same order as the check defs, so walk in the
        # same order to bind them to the right section.
        cursor = 0
        for section_def in _SECTION_DEFS:
            checks = _CHECK_DEFS[section_def["number"]]
            section_id = section_id_by_number[section_def["number"]]
            for _ in checks:
                line_item_rows[cursor].section_id = section_id
                cursor += 1
        session.add_all(line_item_rows)
        await session.commit()


async def _validate_section(
    *,
    adapter: Any,
    section_name: str,
    checks: tuple[_CheckDef, ...],
    context: str,
) -> dict[str, dict[str, Any]]:
    """Call Claude for one section; return `{check_id: {result, confidence}}`."""
    check_lines = [f"- {c['id']}: {c['check']}" for c in checks]
    user_content = (
        f"Section: {section_name}\n"
        f"Checks to evaluate ({len(checks)} total):\n" + "\n".join(check_lines) + "\n\n" + context
    )

    response = await adapter.complete(
        model=settings.anthropic_model,
        messages=[
            {"role": "system", "content": _VALIDATE_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_schema=_VALIDATE_SCHEMA,
    )

    return {
        row["id"]: {"result": row.get("result", ""), "confidence": row.get("confidence", 0)}
        for row in response.get("line_items", [])
        if isinstance(row, dict) and "id" in row
    }


def _format_context(
    *,
    extractions: list[EcvExtraction],
    documents: list[EcvDocument],
) -> str:
    """Render the packet's extractions + doc inventory as a prompt block."""
    if documents:
        doc_lines = [
            f"- #{d.doc_number} {d.name} "
            f"[MISMO {d.mismo_type}, pages {d.pages_display}, status={d.status}]"
            for d in documents
        ]
        doc_block = "Documents found in packet:\n" + "\n".join(doc_lines)
    else:
        doc_block = "Documents found in packet: (none classified)"

    if extractions:
        ex_lines = [
            f"- {e.mismo_path} = {e.value}"
            + (f"  (page {e.page_number})" if e.page_number is not None else "")
            for e in extractions
        ]
        ex_block = "MISMO 3.6 extractions:\n" + "\n".join(ex_lines)
    else:
        ex_block = "MISMO 3.6 extractions: (none — extraction stage returned no fields)"

    return doc_block + "\n\n" + ex_block
