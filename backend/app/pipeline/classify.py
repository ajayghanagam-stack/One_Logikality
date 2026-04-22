"""Real per-page document classification — the `classify` stage.

Reads the files uploaded for a packet, splits them into pages, extracts text
with pypdf, then asks Gemini 2.5 Flash (via Vertex AI) to label each page
with one of the MISMO 3.6 document classes below. Consecutive same-class
pages are grouped into documents.

M2 scope:
- PDF text extraction only. Image-only pages (scans) get empty text and
  fall back to a `quality_issue: low_quality` flag with low confidence —
  real OCR via Vertex Document AI lands in M3.
- 25-class taxonomy mirrors `ecv_data.DOCUMENT_INVENTORY`. If Gemini can't
  place a page in any of them, the enum includes `UNCLASSIFIED`.
- Tests monkeypatch `classify_packet` to avoid calling Vertex; see
  `tests/conftest.py::stub_classify`.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from typing import Any, TypedDict

from pypdf import PdfReader
from sqlalchemy import select

from app.adapters.storage_local import get_storage
from app.config import settings
from app.db import SessionLocal
from app.deps import get_vertex_adapter
from app.models import PacketFile

log = logging.getLogger(__name__)


class ClassifiedDoc(TypedDict, total=False):
    """Shape produced by the classify stage; consumed by `_persist_findings`.

    `name` is a human-readable title Gemini assembles. `mismo_type` is one
    of the 25 MISMO class codes. `pages_display` is a short range string
    (e.g. `"1–5"`) — we keep the en-dash here for UI parity with the demo.
    """

    name: str
    mismo_type: str
    category: str
    pages_display: str
    page_count: int
    confidence: int
    status: str
    page_issue_type: str | None
    page_issue_detail: str | None
    page_issue_affected_page: int | None


# --- Taxonomy ---------------------------------------------------------------
# Keep in lock-step with `app/pipeline/ecv_data.py::DOCUMENT_INVENTORY`.
# Adding a class here without the corresponding required-docs entries (M5)
# will leave the new class classifiable but never required — that's fine for
# optional docs, deliberate for required ones.

_MISMO_CLASSES: tuple[str, ...] = (
    "URLA_1003",
    "CREDIT_REPORT",
    "W2_WAGE_STATEMENT",
    "PAYSTUB",
    "TAX_RETURN_1040",
    "TAX_SCHEDULE_E",
    "BANK_STATEMENT",
    "VOE",
    "IRS_4506T",
    "APPRAISAL",
    "TAX_CERTIFICATE",
    "TITLE_COMMITMENT",
    "WARRANTY_DEED",
    "DEED_OF_TRUST",
    "LOAN_ESTIMATE",
    "CLOSING_DISCLOSURE",
    "HAZARD_INSURANCE",
    "PMI_CERTIFICATE",
    "PROMISSORY_NOTE",
    "LEAD_PAINT_DISCLOSURE",
    "AFFILIATED_BUSINESS",
    "STATE_DISCLOSURE",
    "FLOOD_CERT",
    "UNCLASSIFIED",
)

# Category per MISMO class — used to render the Documents tab's grouping.
_CATEGORY_BY_CLASS: dict[str, str] = {
    "URLA_1003": "Application",
    "CREDIT_REPORT": "Credit",
    "W2_WAGE_STATEMENT": "Income",
    "PAYSTUB": "Income",
    "TAX_RETURN_1040": "Income",
    "TAX_SCHEDULE_E": "Income",
    "BANK_STATEMENT": "Assets",
    "VOE": "Employment",
    "IRS_4506T": "Income",
    "APPRAISAL": "Property",
    "TAX_CERTIFICATE": "Property",
    "TITLE_COMMITMENT": "Title",
    "WARRANTY_DEED": "Title",
    "DEED_OF_TRUST": "Title",
    "LOAN_ESTIMATE": "Disclosure",
    "CLOSING_DISCLOSURE": "Disclosure",
    "HAZARD_INSURANCE": "Insurance",
    "PMI_CERTIFICATE": "Insurance",
    "PROMISSORY_NOTE": "Closing",
    "LEAD_PAINT_DISCLOSURE": "Disclosure",
    "AFFILIATED_BUSINESS": "Disclosure",
    "STATE_DISCLOSURE": "Disclosure",
    "FLOOD_CERT": "Property",
    "UNCLASSIFIED": "Other",
}

_DEFAULT_NAME_BY_CLASS: dict[str, str] = {
    "URLA_1003": "Uniform Residential Loan Application",
    "CREDIT_REPORT": "Credit report",
    "W2_WAGE_STATEMENT": "W-2 Wage Statement",
    "PAYSTUB": "Paystub",
    "TAX_RETURN_1040": "Federal Tax Return 1040",
    "TAX_SCHEDULE_E": "1040 Schedule E — Rental income",
    "BANK_STATEMENT": "Bank statement",
    "VOE": "Verification of Employment",
    "IRS_4506T": "4506-T Tax Transcript Request",
    "APPRAISAL": "Appraisal report",
    "TAX_CERTIFICATE": "Tax certificate",
    "TITLE_COMMITMENT": "Title commitment",
    "WARRANTY_DEED": "Warranty deed",
    "DEED_OF_TRUST": "Deed of trust",
    "LOAN_ESTIMATE": "Loan Estimate (LE)",
    "CLOSING_DISCLOSURE": "Closing Disclosure (CD)",
    "HAZARD_INSURANCE": "Homeowner's insurance policy",
    "PMI_CERTIFICATE": "PMI certificate",
    "PROMISSORY_NOTE": "Promissory note",
    "LEAD_PAINT_DISCLOSURE": "Lead paint disclosure",
    "AFFILIATED_BUSINESS": "AfBA disclosure",
    "STATE_DISCLOSURE": "State-specific disclosure",
    "FLOOD_CERT": "Flood certification",
    "UNCLASSIFIED": "Unclassified document",
}

# --- Prompt + schema --------------------------------------------------------

_CLASSIFY_SYSTEM = (
    "You are a mortgage-document classifier. Given the first ~400 characters "
    "of each page of an uploaded mortgage packet, assign each page to exactly "
    "one MISMO 3.6 document class from the enum. If the page does not match "
    "any class, use UNCLASSIFIED. Provide a confidence (0-100) reflecting how "
    "certain you are based on the text snippet — 90+ for clearly matching "
    "forms, 60-89 for probable matches, below 60 for weak signals. If the "
    "page appears blank or the text extraction returned nothing meaningful, "
    "set quality_issue to blank_page. If the text looks OCR-garbled (random "
    "characters, no coherent words), set quality_issue to low_quality. Only "
    "return the JSON matching the schema — no prose."
)

_CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_number": {
                        "type": "integer",
                        "description": "1-based page number matching the input.",
                    },
                    "mismo_class": {
                        "type": "string",
                        "enum": list(_MISMO_CLASSES),
                    },
                    "doc_title": {
                        "type": "string",
                        "description": (
                            "Short human-readable title for the document this page "
                            "belongs to (e.g. 'W-2 Wage Statement (2025)'). Use an "
                            "empty string for UNCLASSIFIED."
                        ),
                    },
                    "confidence": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "quality_issue": {
                        "type": "string",
                        "enum": ["none", "blank_page", "low_quality", "rotated"],
                    },
                },
                "required": [
                    "page_number",
                    "mismo_class",
                    "confidence",
                    "quality_issue",
                ],
            },
        }
    },
    "required": ["pages"],
}


# Max chars of extracted text we send per page. Flash handles long context,
# but 400 chars is enough to identify mortgage doc types (the top of the
# page usually contains the form name / title / letterhead) and keeps the
# request payload small across ~2000-page packets.
_MAX_CHARS_PER_PAGE = 400

# Max pages per Gemini call. Roughly bounds latency + cost per batch.
_PAGES_PER_BATCH = 50

# Max concurrent Flash classify batches in flight per packet. A 2000-page
# packet fans out to 40 batches; bounding concurrency keeps us from
# overwhelming Vertex quota while still saving minutes over serial
# execution. Tests use stub adapters so this value is irrelevant under test.
_CLASSIFY_CONCURRENCY = 5


# --- Public entrypoint ------------------------------------------------------


async def classify_packet(packet_id: uuid.UUID) -> list[ClassifiedDoc]:
    """Classify every page of a packet's uploaded PDFs.

    First attempts Gemini/Vertex AI classification. If Vertex is unavailable
    (e.g. no GOOGLE_CLOUD_PROJECT in this environment), falls back to a local
    keyword-based heuristic classifier so the Documents tab always shows real
    data derived from the actual uploaded files.
    """
    pages = await _load_packet_pages(packet_id)
    if not pages:
        log.warning("classify: packet %s has no extractable pages", packet_id)
        return []

    try:
        adapter = get_vertex_adapter()
        batches = list(_chunk(pages, _PAGES_PER_BATCH))
        sem = asyncio.Semaphore(_CLASSIFY_CONCURRENCY)

        async def _run(batch: list[_Page]) -> list[dict[str, Any]]:
            async with sem:
                return await _classify_batch(adapter=adapter, pages=batch)

        batch_results = await asyncio.gather(*(_run(b) for b in batches))
        classifications: list[dict[str, Any]] = [c for br in batch_results for c in br]
        classifications.sort(key=lambda c: c["page_number"])
        return _group_into_documents(classifications)
    except Exception:
        log.warning(
            "classify: Vertex AI unavailable for %s — using heuristic classifier",
            packet_id,
        )
        classifications = _heuristic_classify_pages(pages)
        classifications.sort(key=lambda c: c["page_number"])
        return _group_into_documents(classifications)


# --- PDF reading ------------------------------------------------------------


class _Page(TypedDict):
    page_number: int  # global, 1-based across the packet
    text: str


async def _load_packet_pages(packet_id: uuid.UUID) -> list[_Page]:
    """Read all PDFs for a packet and flatten into a single page list."""
    async with SessionLocal() as session:
        files = (
            (
                await session.execute(
                    select(PacketFile)
                    .where(PacketFile.packet_id == packet_id)
                    .order_by(PacketFile.created_at)
                )
            )
            .scalars()
            .all()
        )

    storage = get_storage()
    out: list[_Page] = []
    global_page = 1
    for f in files:
        if f.content_type not in ("application/pdf", "application/x-pdf"):
            # M2 handles PDF only. Images (PNG / JPEG) land in M3 with Document AI.
            log.info(
                "classify: skipping non-PDF file %s (content-type=%s)",
                f.filename,
                f.content_type,
            )
            continue
        try:
            data = await storage.get(f.storage_key)
        except Exception:
            log.exception("classify: failed to read %s from storage", f.storage_key)
            continue

        extracted = await asyncio.to_thread(_extract_pdf_pages, data)
        for text in extracted:
            out.append(_Page(page_number=global_page, text=text))
            global_page += 1
    return out


def _extract_pdf_pages(data: bytes) -> list[str]:
    """pypdf text extraction — runs in a worker thread via asyncio.to_thread.

    Returns per-page text strings. Pages where extraction fails (encrypted,
    corrupt, or image-only) get an empty string so the classifier can tag
    them as `blank_page` / `low_quality` rather than dropping them silently.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        log.exception("pypdf failed to open PDF bytes (%d bytes)", len(data))
        return []
    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(text[:_MAX_CHARS_PER_PAGE].strip())
    return pages


# --- Gemini call ------------------------------------------------------------


async def _classify_batch(
    *,
    adapter: Any,
    pages: list[_Page],
) -> list[dict[str, Any]]:
    """Ask Gemini Flash to classify a batch of pages."""
    lines = [
        f"Page {p['page_number']}:\n{p['text'] if p['text'] else '(no extractable text)'}"
        for p in pages
    ]
    user_content = "\n\n---\n\n".join(lines)

    response = await adapter.complete(
        model=settings.vertex_classify_model,
        messages=[
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_schema=_CLASSIFY_SCHEMA,
    )
    classifications = list(response.get("pages", []))

    # Model sometimes drops pages it can't classify — backfill as UNCLASSIFIED
    # with low confidence so the grouping pass still has every page covered.
    seen = {c["page_number"] for c in classifications}
    for p in pages:
        if p["page_number"] not in seen:
            classifications.append(
                {
                    "page_number": p["page_number"],
                    "mismo_class": "UNCLASSIFIED",
                    "doc_title": "",
                    "confidence": 0,
                    "quality_issue": "low_quality" if not p["text"] else "none",
                }
            )
    return classifications


# --- Grouping ---------------------------------------------------------------


def _group_into_documents(
    classifications: list[dict[str, Any]],
) -> list[ClassifiedDoc]:
    """Merge consecutive same-class pages into documents.

    We break a document whenever (a) the MISMO class changes, OR (b) the
    class stays the same but the `doc_title` changes (e.g. two W-2s from
    different years). Confidence rolls up as the mean of member pages.
    """
    docs: list[ClassifiedDoc] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        cls = current[0]["mismo_class"]
        title = current[0].get("doc_title") or _DEFAULT_NAME_BY_CLASS.get(
            cls, _DEFAULT_NAME_BY_CLASS["UNCLASSIFIED"]
        )
        pages = [c["page_number"] for c in current]
        first, last = pages[0], pages[-1]
        pages_display = f"{first}" if first == last else f"{first}\u2013{last}"
        avg_conf = int(round(sum(c["confidence"] for c in current) / len(current)))

        # Surface the first non-"none" quality issue we saw in this group.
        issue_row = next(
            (c for c in current if c.get("quality_issue", "none") != "none"),
            None,
        )
        issue_type = issue_row["quality_issue"] if issue_row else None
        issue_detail = None
        issue_page = None
        if issue_row is not None:
            issue_detail = (
                f"Page {issue_row['page_number']} flagged as {issue_row['quality_issue']} "
                f"during classification"
            )
            issue_page = issue_row["page_number"]

        docs.append(
            ClassifiedDoc(
                name=title,
                mismo_type=cls,
                category=_CATEGORY_BY_CLASS.get(cls, "Other"),
                pages_display=pages_display,
                page_count=len(pages),
                confidence=max(0, min(100, avg_conf)),
                status="found",
                page_issue_type=issue_type,
                page_issue_detail=issue_detail,
                page_issue_affected_page=issue_page,
            )
        )

    for c in classifications:
        if not current:
            current.append(c)
            continue
        last = current[-1]
        same_class = c["mismo_class"] == last["mismo_class"]
        same_title = (c.get("doc_title") or "") == (last.get("doc_title") or "")
        if same_class and same_title:
            current.append(c)
        else:
            flush()
            current = [c]
    flush()
    return docs


def _chunk(items: list[_Page], size: int) -> list[list[_Page]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# --- Heuristic (no-AI) classifier -------------------------------------------
# Used when Vertex AI is unavailable. Keyword/pattern matching on extracted
# text to produce real per-page classifications from the actual uploaded PDFs.

_HEURISTIC_RULES: list[tuple[str, list[str]]] = [
    # Order matters — first match wins.
    ("URLA_1003",            ["uniform residential loan application", "fannie mae form 1003", "freddie mac form 65"]),
    ("CLOSING_DISCLOSURE",   ["closing disclosure", "projected payments", "loan costs", "other costs"]),
    ("LOAN_ESTIMATE",        ["loan estimate", "projected payments", "estimated total monthly payment"]),
    ("PROMISSORY_NOTE",      ["promissory note", "promise to pay", "principal amount", "borrower promises"]),
    ("DEED_OF_TRUST",        ["deed of trust", "trustee", "beneficiary", "security instrument"]),
    ("WARRANTY_DEED",        ["warranty deed", "grantor", "grantee", "conveys and warrants"]),
    ("TITLE_COMMITMENT",     ["title commitment", "schedule a", "schedule b", "title insurance"]),
    ("CREDIT_REPORT",        ["credit report", "equifax", "transunion", "experian", "fico score", "credit score"]),
    ("W2_WAGE_STATEMENT",    ["w-2", "wage and tax statement", "omb no. 1545-0008", "employer identification"]),
    ("PAYSTUB",              ["pay stub", "earnings statement", "pay period", "ytd earnings", "gross pay", "net pay"]),
    ("TAX_RETURN_1040",      ["form 1040", "u.s. individual income tax return", "adjusted gross income", "schedule 1"]),
    ("TAX_SCHEDULE_E",       ["schedule e", "supplemental income and loss", "rental income", "royalties"]),
    ("BANK_STATEMENT",       ["account statement", "bank statement", "beginning balance", "ending balance", "deposits"]),
    ("VOE",                  ["verification of employment", "employment verification", "dates of employment"]),
    ("IRS_4506T",            ["4506-t", "request for transcript", "tax transcript", "irs transcript"]),
    ("APPRAISAL",            ["appraisal report", "uniform residential appraisal", "subject property", "appraised value"]),
    ("TAX_CERTIFICATE",      ["tax certificate", "tax collector", "property tax", "ad valorem"]),
    ("HAZARD_INSURANCE",     ["homeowner", "hazard insurance", "insurance policy", "policy number", "dwelling coverage"]),
    ("PMI_CERTIFICATE",      ["pmi", "private mortgage insurance", "mortgage insurance certificate"]),
    ("LEAD_PAINT_DISCLOSURE",["lead-based paint", "lead paint", "disclosure of information on lead"]),
    ("AFFILIATED_BUSINESS",  ["affiliated business", "afba", "settlement service provider"]),
    ("FLOOD_CERT",           ["flood certification", "national flood", "fema", "flood zone", "flood determination"]),
    ("STATE_DISCLOSURE",     ["state disclosure", "real estate transfer", "state-specific", "disclosure statement"]),
]


def _heuristic_classify_page(text: str) -> tuple[str, int]:
    """Return (mismo_class, confidence) for a single page using keyword matching."""
    lower = text.lower()
    if not lower.strip():
        return "UNCLASSIFIED", 0
    for mismo_class, keywords in _HEURISTIC_RULES:
        hits = sum(1 for kw in keywords if kw in lower)
        if hits >= 2:
            return mismo_class, min(85 + hits * 2, 95)
        if hits == 1:
            return mismo_class, 72
    return "UNCLASSIFIED", 45


def _heuristic_classify_pages(pages: list[_Page]) -> list[dict[str, Any]]:
    """Classify all pages heuristically; feed into existing _group_into_documents."""
    results: list[dict[str, Any]] = []
    for p in pages:
        mismo_class, confidence = _heuristic_classify_page(p["text"])
        quality = "blank_page" if not p["text"].strip() else "none"
        results.append({
            "page_number": p["page_number"],
            "mismo_class": mismo_class,
            "doc_title": _DEFAULT_NAME_BY_CLASS.get(mismo_class, ""),
            "confidence": confidence,
            "quality_issue": quality,
        })
    return results
