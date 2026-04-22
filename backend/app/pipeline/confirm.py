"""Real AI-driven loan-program confirmation — runs after the extract stage.

Reads the `EcvDocument` rows (what document types were found) and
`EcvExtraction` rows (what field values Gemini Pro pulled out) that the
classify + extract stages already persisted, then asks Gemini Flash to
decide whether those documents confirm, conflict-with, or are inconclusive
about the declared loan program.

The result is written back to the `Packet` row exactly as the canned
`CONFIRMATION_BY_PROGRAM` lookup did before — same four columns —
so the rest of the pipeline and the frontend are unchanged.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, update

from app.config import settings
from app.db import SessionLocal
from app.deps import get_vertex_adapter
from app.models import EcvDocument, EcvExtraction, Packet

log = logging.getLogger(__name__)

# Known loan program IDs the classifier may suggest.
_PROGRAM_IDS = ("conventional", "jumbo", "fha", "va", "usda", "nonqm")

_CONFIRM_SYSTEM = """\
You are a senior mortgage compliance analyst.
You will be given:
  1. The loan program the borrower declared when submitting the packet.
  2. A list of document types that were found in the packet (MISMO 3.6 class names).
  3. Key field values extracted from those documents (loan amount, program identifiers, etc.).

Your job is to decide whether the documents in the packet CONFIRM, CONFLICT with,
or are INCONCLUSIVE about the declared program.

Definitions:
- confirmed  : The documents are consistent with the declared program. The evidence
               supports the program eligibility criteria.
- conflict   : The documents clearly indicate a different program applies.
- inconclusive: Not enough program-distinguishing information is present to make a
               determination.

Return ONLY valid JSON matching this exact schema — no prose, no markdown:
{
  "status": "<confirmed|conflict|inconclusive>",
  "suggested_program_id": "<conventional|jumbo|fha|va|usda|nonqm|null>",
  "evidence": "<1-3 sentence plain-English explanation citing specific values and documents found>",
  "documents_analyzed": ["<doc type 1>", "<doc type 2>"]
}

Rules:
- "suggested_program_id" must be null when status is "confirmed" or "inconclusive".
- "documents_analyzed" should list 2-5 document types that were most relevant to your decision.
- "evidence" must cite specific values from the extractions (e.g. actual loan amount, actual
  conforming limit used, presence/absence of specific documents or case numbers).
- Be concise but specific. Do not use placeholder values.
- Use the current FHFA 2026 conforming loan limit of $806,500 for single-family properties
  unless a county-specific limit applies.
"""


async def confirm_program(packet_id: uuid.UUID) -> None:
    """Run real AI program confirmation for a packet.

    Reads classified documents + MISMO extractions already in the DB, calls
    Gemini Flash to produce a verdict, and writes the four
    program_confirmation_* columns back onto the Packet row.

    Swallows all errors — on failure the columns remain NULL and the
    frontend renders the "Awaiting ECV" placeholder.
    """
    try:
        await _confirm_program(packet_id)
    except Exception:
        log.exception("confirm_program failed for packet %s", packet_id)


async def _confirm_program(packet_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        packet = (
            await session.execute(
                select(Packet.declared_program_id, Packet.org_id).where(Packet.id == packet_id)
            )
        ).one_or_none()
        if packet is None:
            log.warning("confirm: packet %s not found", packet_id)
            return

        declared_program_id, _org_id = packet

        # --- Gather documents -----------------------------------------------
        docs = (
            (
                await session.execute(
                    select(EcvDocument.mismo_type, EcvDocument.name, EcvDocument.status)
                    .where(EcvDocument.packet_id == packet_id)
                    .order_by(EcvDocument.sort_order)
                )
            )
            .all()
        )

        # --- Gather key extractions -----------------------------------------
        # Pull every extraction so Gemini can see the real loan amount, program
        # type codes, case numbers, etc. Limit to 60 rows — more than enough
        # to determine program eligibility.
        extractions = (
            (
                await session.execute(
                    select(
                        EcvExtraction.mismo_path,
                        EcvExtraction.field,
                        EcvExtraction.value,
                        EcvExtraction.snippet,
                    )
                    .where(EcvExtraction.packet_id == packet_id)
                    .order_by(EcvExtraction.mismo_path)
                    .limit(60)
                )
            )
            .all()
        )

    # --- Build prompt -------------------------------------------------------
    doc_lines = "\n".join(
        f"  - {d.mismo_type} ({d.name}) [status: {d.status}]"
        for d in docs
    ) or "  (no documents classified)"

    ext_lines = "\n".join(
        f"  - {e.field}: {e.value!r}  [path: {e.mismo_path}]"
        + (f"  snippet: {e.snippet!r}" if e.snippet else "")
        for e in extractions
    ) or "  (no extractions available)"

    user_msg = (
        f"Declared loan program: {declared_program_id}\n\n"
        f"Documents found in packet:\n{doc_lines}\n\n"
        f"Key extracted field values:\n{ext_lines}\n\n"
        f"Known loan program IDs: {', '.join(_PROGRAM_IDS)}\n\n"
        "Based on the above, produce the JSON verdict."
    )

    adapter = get_vertex_adapter()
    response: dict[str, Any] = await adapter.complete(
        model=settings.vertex_classify_model,
        messages=[
            {"role": "system", "content": _CONFIRM_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["confirmed", "conflict", "inconclusive"],
                },
                "suggested_program_id": {"type": "string"},
                "evidence": {"type": "string"},
                "documents_analyzed": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["status", "evidence", "documents_analyzed"],
        },
    )

    status = response.get("status", "inconclusive")
    suggested = response.get("suggested_program_id") or None
    # Normalise: null-ish strings → None
    if suggested and suggested.lower() in ("null", "none", ""):
        suggested = None
    evidence: str = response.get("evidence", "")
    analyzed: list[str] = response.get("documents_analyzed", [])

    if not evidence:
        log.warning("confirm: Gemini returned empty evidence for packet %s", packet_id)
        return

    log.info(
        "confirm: packet %s → status=%s suggested=%s", packet_id, status, suggested
    )

    async with SessionLocal() as session:
        await session.execute(
            update(Packet)
            .where(Packet.id == packet_id)
            .values(
                program_confirmation_status=status,
                program_confirmation_suggested_id=suggested,
                program_confirmation_evidence=evidence,
                program_confirmation_documents=analyzed,
            )
        )
        await session.commit()
