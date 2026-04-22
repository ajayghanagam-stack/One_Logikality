"""Real per-document MISMO 3.6 field extraction — the `extract` stage.

For each `EcvDocument` row produced by the `classify` stage, ask Gemini 2.5
Pro (via Vertex AI) to read the pages belonging to that document and emit
MISMO 3.6 extractions with page-level evidence. Results are persisted as
`EcvExtraction` rows (one per (document, MISMO path) pair) so the MISMO
panel (US-7.3) and evidence panel (US-7.4) can render real data instead of
canned strings.

M3 scope:
- Pipes pypdf text (same path classify uses). Real OCR via Vertex Document
  AI for scanned forms is deferred — Gemini Pro over pypdf text is enough
  to satisfy M3's acceptance criteria for born-digital packets.
- Skips documents flagged `UNCLASSIFIED` (nothing to extract) and docs with
  `status != "found"` (canned missing-doc inventory has no pages).
- Tests monkeypatch `extract_packet` to avoid calling Vertex; see
  `tests/conftest.py::_stub_extract`.

RLS: writes bypass RLS by running as postgres superuser — same design as
the classify stage; this is server-internal orchestration, not a
tenant-scoped request.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, TypedDict

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.deps import get_vertex_adapter
from app.models import EcvDocument, EcvExtraction, Packet
from app.pipeline.classify import _load_packet_pages

log = logging.getLogger(__name__)


class ExtractedField(TypedDict, total=False):
    mismo_path: str
    entity: str
    field: str
    value: str
    confidence: int
    page_number: int | None
    snippet: str | None


# Max chars of extracted text we send per page. Pro handles a 2M-token
# context window; 4,000 chars/page × ~50 pages/doc is well within limits
# and keeps field names, labels, and values intact after pypdf's layout
# flattening. Raising this further rarely improves extraction quality
# for mortgage forms, which are mostly label-value pairs at the top.
_MAX_CHARS_PER_PAGE = 4000


_EXTRACT_SYSTEM = (
    "You are a mortgage document data-extraction model. Given the text of "
    "pages belonging to a single mortgage document (classified as the "
    "MISMO 3.6 type in the user message), extract every MISMO 3.6 field "
    "you can locate on the pages and return them as structured data.\n\n"
    "For each extraction, return:\n"
    "- mismo_path: the full dotted MISMO 3.6 path (e.g. "
    "'DEAL.LOANS.LOAN[1].TERMS_OF_LOAN.LoanAmount'). Use MISMO 3.6 entity "
    "names and capitalization exactly.\n"
    "- entity: just the top-level MISMO entity the field lives under "
    "(e.g. 'LOAN', 'PARTY', 'COLLATERAL', 'PROPERTY').\n"
    "- field: the leaf field name (e.g. 'LoanAmount', 'FullName').\n"
    "- value: the value as it appears on the page. Keep currency symbols "
    "and punctuation as written; do not reformat.\n"
    "- confidence: 0-100 — how confident you are the value is correct "
    "based on the textual evidence. 90+ for values clearly labelled and "
    "legible, 60-89 for probable reads, below 60 for weak signals.\n"
    "- page_number: the 1-based global packet page number on which the "
    "value appears (pick the page containing the label+value).\n"
    "- snippet: a short (<=160 char) verbatim excerpt from the page that "
    "contains the value — the evidence the value was read from.\n\n"
    "Only emit fields you actually see. Do not invent MISMO paths. If a "
    "page is blank or contains no recognizable mortgage fields, emit "
    "nothing for it. Return only the JSON matching the schema — no prose."
)

_EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "extractions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mismo_path": {"type": "string"},
                    "entity": {"type": "string"},
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "page_number": {"type": "integer"},
                    "snippet": {"type": "string"},
                },
                "required": [
                    "mismo_path",
                    "entity",
                    "field",
                    "value",
                    "confidence",
                ],
            },
        }
    },
    "required": ["extractions"],
}


async def extract_packet(packet_id: uuid.UUID) -> None:
    """Run MISMO extraction across every classified document in a packet.

    Persists `EcvExtraction` rows. Idempotent by convention: callers
    (`_persist_findings`) already gate on whether findings exist for the
    packet, so re-entry is not expected during normal operation; on
    replay, the caller is responsible for clearing prior rows if needed.

    Failures are logged and swallowed per-document so one bad document
    doesn't sink the rest of the extraction.
    """
    async with SessionLocal() as session:
        packet_org = (
            await session.execute(select(Packet.org_id).where(Packet.id == packet_id))
        ).scalar_one_or_none()
        if packet_org is None:
            log.warning("extract: packet %s vanished before extraction", packet_id)
            return

        docs = (
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

    if not docs:
        log.info("extract: packet %s has no classified documents", packet_id)
        return

    pages = await _load_packet_pages(packet_id)
    if not pages:
        log.info("extract: packet %s has no extractable pages", packet_id)
        return

    # Index packet pages by global 1-based page number for O(1) slicing
    # per document.
    pages_by_number: dict[int, str] = {p["page_number"]: p["text"] for p in pages}

    adapter = get_vertex_adapter()
    all_rows: list[EcvExtraction] = []
    for doc in docs:
        if doc.status != "found":
            continue
        if doc.mismo_type == "UNCLASSIFIED":
            continue
        page_range = _parse_pages_range(doc.pages_display)
        if page_range is None:
            log.warning(
                "extract: could not parse pages_display=%r for doc %s",
                doc.pages_display,
                doc.id,
            )
            continue
        first, last = page_range
        doc_pages: list[tuple[int, str]] = []
        for n in range(first, last + 1):
            text = pages_by_number.get(n, "")
            if text:
                doc_pages.append((n, text[:_MAX_CHARS_PER_PAGE]))
        if not doc_pages:
            # Image-only doc (scan) — pypdf returned empty text. Document
            # AI lands later; for now skip rather than ask Gemini to
            # hallucinate fields from nothing.
            continue

        try:
            extractions = await _extract_document(
                adapter=adapter,
                mismo_type=doc.mismo_type,
                doc_name=doc.name,
                pages=doc_pages,
            )
        except Exception:
            log.exception("extract: Gemini call failed for doc %s (%s)", doc.id, doc.mismo_type)
            continue

        for e in extractions:
            # Belt-and-suspenders — the response schema already bounds
            # confidence, but drop malformed rows rather than trip the
            # CHECK constraint and blow up the whole commit.
            conf = int(e.get("confidence", 0))
            if conf < 0 or conf > 100:
                continue
            page_number = e.get("page_number")
            # Page numbers must fall inside the document's claimed range;
            # Gemini occasionally attributes a value to the wrong page.
            if page_number is not None and not (first <= page_number <= last):
                page_number = None
            all_rows.append(
                EcvExtraction(
                    packet_id=packet_id,
                    org_id=packet_org,
                    document_id=doc.id,
                    mismo_path=e["mismo_path"],
                    entity=e["entity"],
                    field=e["field"],
                    value=e["value"],
                    confidence=conf,
                    page_number=page_number,
                    snippet=e.get("snippet"),
                )
            )

    if not all_rows:
        log.info("extract: packet %s produced no extractions", packet_id)
        return

    async with SessionLocal() as session:
        session.add_all(all_rows)
        await session.commit()


async def _extract_document(
    *,
    adapter: Any,
    mismo_type: str,
    doc_name: str,
    pages: list[tuple[int, str]],
) -> list[ExtractedField]:
    """Ask Gemini Pro to extract MISMO fields from one document's pages."""
    lines = [f"Page {n}:\n{text}" for n, text in pages]
    user_content = (
        f"Document: {doc_name}\n"
        f"MISMO 3.6 class: {mismo_type}\n"
        f"Number of pages: {len(pages)}\n\n"
        "Pages follow below, separated by '---'. Extract every MISMO 3.6 "
        "field present.\n\n" + "\n\n---\n\n".join(lines)
    )

    response = await adapter.complete(
        model=settings.vertex_extract_model,
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_schema=_EXTRACT_SCHEMA,
    )
    return list(response.get("extractions", []))


def _parse_pages_range(pages_display: str) -> tuple[int, int] | None:
    """Parse a pages_display string back to (first, last) page numbers.

    classify.py emits `"1"` for a single page and `"1\u20135"` (en-dash)
    for a range. Also tolerates a hyphen or em-dash in case human-edited
    or legacy canned rows slip through.
    """
    s = pages_display.strip().replace("\u2013", "-").replace("\u2014", "-")
    if "-" in s:
        a, b = s.split("-", 1)
        try:
            return int(a.strip()), int(b.strip())
        except ValueError:
            return None
    try:
        v = int(s)
    except ValueError:
        return None
    return v, v
