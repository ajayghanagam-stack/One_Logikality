"""Deterministic canned ECV findings.

Ported 1:1 from the `one-logikality-demo` reference (`lib/demo-data.ts`
-> `ECV_SECTIONS`, `ECV_LINE_ITEMS`, `DOCUMENT_INVENTORY`) so the
dashboard reads the same numbers end-to-end. The ECV stub writes these
rows to the `ecv_sections`, `ecv_line_items`, and `ecv_documents` tables
during the `score` stage.

When the real Temporal ECV workflow lands it will replace the stub entry
point but can keep this module around as the fallback / seed for
development environments where running the full pipeline isn't
practical.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class _Section(TypedDict):
    id: int
    name: str
    score: int
    weight: int


class _LineItem(TypedDict):
    id: str
    check: str
    result: str
    confidence: int


class _PageIssue(TypedDict):
    type: Literal["blank_page", "low_quality", "rotated"]
    detail: str
    affected_page: int


class _Document(TypedDict, total=False):
    id: int
    name: str
    mismo_type: str
    pages: str
    page_count: int
    confidence: int
    status: Literal["found", "missing"]
    category: str
    page_issue: _PageIssue | None


# 13 sections, total weight 100 (matches the demo exactly).
ECV_SECTIONS: tuple[_Section, ...] = (
    {"id": 1, "name": "Document completeness", "score": 95, "weight": 8},
    {"id": 2, "name": "Borrower identity", "score": 80, "weight": 12},
    {"id": 3, "name": "Property consistency", "score": 92, "weight": 10},
    {"id": 4, "name": "Loan terms", "score": 97, "weight": 15},
    {"id": 5, "name": "Financial / underwriting", "score": 88, "weight": 15},
    {"id": 6, "name": "Appraisal", "score": 91, "weight": 10},
    {"id": 7, "name": "Title & legal", "score": 85, "weight": 8},
    {"id": 8, "name": "Regulatory compliance", "score": 76, "weight": 10},
    {"id": 9, "name": "Signatures & dates", "score": 94, "weight": 5},
    {"id": 10, "name": "Insurance", "score": 100, "weight": 3},
    {"id": 11, "name": "Document quality", "score": 89, "weight": 2},
    {"id": 12, "name": "Condition clearance", "score": 70, "weight": 2},
    {"id": 13, "name": "Cross-doc reconciliation", "score": 93, "weight": 0},
)


# 58 line items, keyed by section_number -> list of checks. Confidence
# values are intentionally uneven so the Items-to-Review tab has real
# data to classify (critical < 50%, amber 50–84%, pass >= 85%).
ECV_LINE_ITEMS: dict[int, tuple[_LineItem, ...]] = {
    1: (
        {
            "id": "1.1",
            "check": "All 25 required documents present",
            "result": "23/25 found",
            "confidence": 88,
        },
        {
            "id": "1.2",
            "check": "No missing pages within documents",
            "result": "All pages sequential",
            "confidence": 97,
        },
        {
            "id": "1.3",
            "check": "Required addenda & riders attached",
            "result": "All present",
            "confidence": 99,
        },
        {
            "id": "1.4",
            "check": "All signature pages included",
            "result": "Complete",
            "confidence": 96,
        },
    ),
    2: (
        {
            "id": "2.1",
            "check": "Borrower name matches across all docs",
            "result": "Match across 18 docs",
            "confidence": 98,
        },
        {
            "id": "2.2",
            "check": "SSN matches on application, credit, tax, 4506-T",
            "result": "Match 3/4, one illegible",
            "confidence": 82,
        },
        {
            "id": "2.3",
            "check": "DOB consistent across documents",
            "result": "Full match",
            "confidence": 99,
        },
        {
            "id": "2.4",
            "check": "Marital status consistent",
            "result": "MISMATCH: Single vs Married",
            "confidence": 35,
        },
        {
            "id": "2.5",
            "check": "Address history matches",
            "result": "Prior address missing on 1 doc",
            "confidence": 74,
        },
    ),
    3: (
        {
            "id": "3.1",
            "check": "Property address matches on every document",
            "result": "Full match",
            "confidence": 97,
        },
        {
            "id": "3.2",
            "check": "Legal description matches deed, title, appraisal",
            "result": "Match",
            "confidence": 94,
        },
        {"id": "3.3", "check": "Parcel/APN number consistent", "result": "Match", "confidence": 96},
        {
            "id": "3.4",
            "check": "Property type consistent (SFR/Condo/Multi)",
            "result": "SFR on all",
            "confidence": 99,
        },
    ),
    4: (
        {
            "id": "4.1",
            "check": "Loan amount matches across LE, CD, Note, Deed",
            "result": "$385,000 — Full match",
            "confidence": 100,
        },
        {
            "id": "4.2",
            "check": "Interest rate consistent",
            "result": "6.75% — Full match",
            "confidence": 100,
        },
        {
            "id": "4.3",
            "check": "Loan term matches",
            "result": "30yr — Full match",
            "confidence": 99,
        },
        {
            "id": "4.4",
            "check": "Monthly P&I calculates correctly",
            "result": "$2,497.21 — Verified",
            "confidence": 98,
        },
        {
            "id": "4.5",
            "check": "Escrow amounts for tax/insurance match",
            "result": "Match",
            "confidence": 91,
        },
    ),
    5: (
        {
            "id": "5.1",
            "check": "W-2 income reconciles with application",
            "result": "$112,400 — Match",
            "confidence": 96,
        },
        {
            "id": "5.2",
            "check": "DTI ratio within guidelines",
            "result": "38.2% — Within limit",
            "confidence": 92,
        },
        {
            "id": "5.3",
            "check": "Bank statements support down payment & reserves",
            "result": "Sufficient funds verified",
            "confidence": 89,
        },
        {"id": "5.4", "check": "Gift letter properly executed", "result": "N/A", "confidence": 100},
        {
            "id": "5.5",
            "check": "Employment VOE matches application",
            "result": "Title mismatch: Analyst vs Sr. Analyst",
            "confidence": 72,
        },
    ),
    6: (
        {
            "id": "6.1",
            "check": "Appraised value supports LTV ratio",
            "result": "$410,000 — LTV 93.9%",
            "confidence": 95,
        },
        {
            "id": "6.2",
            "check": "Appraisal dated within acceptable window",
            "result": "Dated 62 days ago",
            "confidence": 94,
        },
        {
            "id": "6.3",
            "check": "Comparable sales appropriate",
            "result": "3 comps within 1mi",
            "confidence": 88,
        },
        {
            "id": "6.4",
            "check": "Appraiser licensed for state",
            "result": "IL License #553-002187",
            "confidence": 97,
        },
    ),
    7: (
        {
            "id": "7.1",
            "check": "Title clear of unexpected liens",
            "result": "Clear",
            "confidence": 92,
        },
        {
            "id": "7.2",
            "check": "Prior mortgages satisfied",
            "result": "Satisfaction recorded",
            "confidence": 88,
        },
        {"id": "7.3", "check": "Vesting correct", "result": "Match", "confidence": 90},
        {
            "id": "7.4",
            "check": "Title commitment matches final policy",
            "result": "Pending final review",
            "confidence": 78,
        },
    ),
    8: (
        {
            "id": "8.1",
            "check": "Loan Estimate delivered within 3 business days",
            "result": "Delivered Day 2",
            "confidence": 96,
        },
        {
            "id": "8.2",
            "check": "Closing Disclosure delivered 3 days before closing",
            "result": "Timing unclear — date stamp missing",
            "confidence": 62,
        },
        {
            "id": "8.3",
            "check": "Fee tolerance checks (0%, 10%, unlimited)",
            "result": "Within tolerance",
            "confidence": 88,
        },
        {
            "id": "8.4",
            "check": "State-specific disclosures present",
            "result": "IL disclosures — 2/3 found",
            "confidence": 68,
        },
    ),
    9: (
        {
            "id": "9.1",
            "check": "All parties signed required documents",
            "result": "Complete",
            "confidence": 97,
        },
        {
            "id": "9.2",
            "check": "Signatures consistent across documents",
            "result": "Consistent",
            "confidence": 93,
        },
        {
            "id": "9.3",
            "check": "Dates logical and chronological",
            "result": "All dates in order",
            "confidence": 96,
        },
        {
            "id": "9.4",
            "check": "Notarization valid (seal, commission, state)",
            "result": "Valid — expires 2027",
            "confidence": 98,
        },
    ),
    10: (
        {
            "id": "10.1",
            "check": "Hazard insurance in force",
            "result": "Policy active",
            "confidence": 100,
        },
        {
            "id": "10.2",
            "check": "Lender listed as mortgagee",
            "result": "Confirmed",
            "confidence": 100,
        },
        {
            "id": "10.3",
            "check": "Flood insurance (if required)",
            "result": "Not in flood zone",
            "confidence": 100,
        },
        {
            "id": "10.4",
            "check": "PMI disclosed and in place",
            "result": "PMI active — LTV > 80%",
            "confidence": 100,
        },
    ),
    11: (
        {
            "id": "11.1",
            "check": "All pages legible",
            "result": "2 pages low resolution",
            "confidence": 78,
        },
        {
            "id": "11.2",
            "check": "No signs of alteration or tampering",
            "result": "Clean",
            "confidence": 96,
        },
        {
            "id": "11.3",
            "check": "Correct orientation on all pages",
            "result": "3 pages rotated",
            "confidence": 82,
        },
        {
            "id": "11.4",
            "check": "No DRAFT watermarks on final docs",
            "result": "Clean",
            "confidence": 100,
        },
    ),
    12: (
        {
            "id": "12.1",
            "check": "Prior-to-doc conditions satisfied",
            "result": "4/4 cleared",
            "confidence": 95,
        },
        {
            "id": "12.2",
            "check": "Prior-to-funding conditions satisfied",
            "result": "2/3 cleared",
            "confidence": 68,
        },
        {
            "id": "12.3",
            "check": "All conditions documented with evidence",
            "result": "PTF #4 missing docs",
            "confidence": 48,
        },
    ),
    13: (
        {
            "id": "13.1",
            "check": "CD closing costs match settlement statement",
            "result": "Match",
            "confidence": 96,
        },
        {
            "id": "13.2",
            "check": "Prorated taxes calculate correctly",
            "result": "Verified",
            "confidence": 94,
        },
        {
            "id": "13.3",
            "check": "Cash-to-close reconciles",
            "result": "$42,318 — Reconciled",
            "confidence": 97,
        },
        {
            "id": "13.4",
            "check": "Prepaid interest calculates correctly",
            "result": "Verified",
            "confidence": 93,
        },
    ),
}


# 25-doc MISMO inventory: 23 found, 2 missing. Mirrors demo's
# `DOCUMENT_INVENTORY`.
DOCUMENT_INVENTORY: tuple[_Document, ...] = (
    {
        "id": 1,
        "name": "Uniform Residential Loan Application",
        "mismo_type": "URLA_1003",
        "pages": "1–5",
        "page_count": 5,
        "confidence": 98,
        "status": "found",
        "category": "Application",
        "page_issue": None,
    },
    {
        "id": 2,
        "name": "Credit report (tri-merge)",
        "mismo_type": "CREDIT_REPORT",
        "pages": "6–14",
        "page_count": 9,
        "confidence": 97,
        "status": "found",
        "category": "Credit",
        "page_issue": None,
    },
    {
        "id": 3,
        "name": "W-2 Wage Statement (2025)",
        "mismo_type": "W2_WAGE_STATEMENT",
        "pages": "15–16",
        "page_count": 2,
        "confidence": 96,
        "status": "found",
        "category": "Income",
        "page_issue": None,
    },
    {
        "id": 4,
        "name": "W-2 Wage Statement (2024)",
        "mismo_type": "W2_WAGE_STATEMENT",
        "pages": "17–18",
        "page_count": 2,
        "confidence": 95,
        "status": "found",
        "category": "Income",
        "page_issue": None,
    },
    {
        "id": 5,
        "name": "Paystub (Mar 2026)",
        "mismo_type": "PAYSTUB",
        "pages": "19–20",
        "page_count": 2,
        "confidence": 94,
        "status": "found",
        "category": "Income",
        "page_issue": None,
    },
    {
        "id": 6,
        "name": "Federal Tax Return 1040 (2025)",
        "mismo_type": "TAX_RETURN_1040",
        "pages": "21–36",
        "page_count": 16,
        "confidence": 93,
        "status": "found",
        "category": "Income",
        "page_issue": {
            "type": "blank_page",
            "detail": "Page 29 is blank — expected Schedule C continuation",
            "affected_page": 29,
        },
    },
    {
        "id": 7,
        "name": "Federal Tax Return 1040 (2024)",
        "mismo_type": "TAX_RETURN_1040",
        "pages": "37–52",
        "page_count": 16,
        "confidence": 92,
        "status": "found",
        "category": "Income",
        "page_issue": None,
    },
    {
        "id": 8,
        "name": "Bank statements (3 months)",
        "mismo_type": "BANK_STATEMENT",
        "pages": "53–68",
        "page_count": 16,
        "confidence": 91,
        "status": "found",
        "category": "Assets",
        "page_issue": {
            "type": "low_quality",
            "detail": (
                "Pages 61–62 are low resolution (scanned at 72 DPI) — text partially illegible"
            ),
            "affected_page": 61,
        },
    },
    {
        "id": 9,
        "name": "Verification of Employment (VOE)",
        "mismo_type": "VOE",
        "pages": "69–70",
        "page_count": 2,
        "confidence": 89,
        "status": "found",
        "category": "Employment",
        "page_issue": None,
    },
    {
        "id": 10,
        "name": "4506-T Tax Transcript Request",
        "mismo_type": "IRS_4506T",
        "pages": "71–72",
        "page_count": 2,
        "confidence": 97,
        "status": "found",
        "category": "Income",
        "page_issue": None,
    },
    {
        "id": 11,
        "name": "Appraisal report",
        "mismo_type": "APPRAISAL",
        "pages": "73–102",
        "page_count": 30,
        "confidence": 96,
        "status": "found",
        "category": "Property",
        "page_issue": {
            "type": "rotated",
            "detail": "Pages 88–89 are rotated 90° — comparable sales photos oriented sideways",
            "affected_page": 88,
        },
    },
    {
        "id": 12,
        "name": "Tax certificate",
        "mismo_type": "TAX_CERTIFICATE",
        "pages": "103–104",
        "page_count": 2,
        "confidence": 95,
        "status": "found",
        "category": "Property",
        "page_issue": None,
    },
    {
        "id": 13,
        "name": "Title commitment",
        "mismo_type": "TITLE_COMMITMENT",
        "pages": "105–118",
        "page_count": 14,
        "confidence": 97,
        "status": "found",
        "category": "Title",
        "page_issue": None,
    },
    {
        "id": 14,
        "name": "Warranty deed (current)",
        "mismo_type": "WARRANTY_DEED",
        "pages": "119–122",
        "page_count": 4,
        "confidence": 94,
        "status": "found",
        "category": "Title",
        "page_issue": None,
    },
    {
        "id": 15,
        "name": "Deed of trust (prior mortgage)",
        "mismo_type": "DEED_OF_TRUST",
        "pages": "123–136",
        "page_count": 14,
        "confidence": 93,
        "status": "found",
        "category": "Title",
        "page_issue": None,
    },
    {
        "id": 16,
        "name": "Loan Estimate (LE)",
        "mismo_type": "LOAN_ESTIMATE",
        "pages": "137–142",
        "page_count": 6,
        "confidence": 98,
        "status": "found",
        "category": "Disclosure",
        "page_issue": None,
    },
    {
        "id": 17,
        "name": "Closing Disclosure (CD)",
        "mismo_type": "CLOSING_DISCLOSURE",
        "pages": "143–150",
        "page_count": 8,
        "confidence": 97,
        "status": "found",
        "category": "Disclosure",
        "page_issue": None,
    },
    {
        "id": 18,
        "name": "Homeowner's insurance policy",
        "mismo_type": "HAZARD_INSURANCE",
        "pages": "151–158",
        "page_count": 8,
        "confidence": 96,
        "status": "found",
        "category": "Insurance",
        "page_issue": None,
    },
    {
        "id": 19,
        "name": "PMI certificate",
        "mismo_type": "PMI_CERTIFICATE",
        "pages": "159–160",
        "page_count": 2,
        "confidence": 94,
        "status": "found",
        "category": "Insurance",
        "page_issue": None,
    },
    {
        "id": 20,
        "name": "Promissory note",
        "mismo_type": "PROMISSORY_NOTE",
        "pages": "161–166",
        "page_count": 6,
        "confidence": 98,
        "status": "found",
        "category": "Closing",
        "page_issue": None,
    },
    {
        "id": 21,
        "name": "Lead paint disclosure",
        "mismo_type": "LEAD_PAINT_DISCLOSURE",
        "pages": "167–168",
        "page_count": 2,
        "confidence": 94,
        "status": "found",
        "category": "Disclosure",
        "page_issue": None,
    },
    {
        "id": 22,
        "name": "AfBA disclosure",
        "mismo_type": "AFFILIATED_BUSINESS",
        "pages": "169–170",
        "page_count": 2,
        "confidence": 91,
        "status": "found",
        "category": "Disclosure",
        "page_issue": None,
    },
    {
        "id": 23,
        "name": "1040 Schedule E — Rental income",
        "mismo_type": "TAX_SCHEDULE_E",
        "pages": "171–174",
        "page_count": 4,
        "confidence": 88,
        "status": "found",
        "category": "Income",
        "page_issue": None,
    },
    {
        "id": 24,
        "name": "Radon disclosure (IL required)",
        "mismo_type": "STATE_DISCLOSURE",
        "pages": "—",
        "page_count": 0,
        "confidence": 0,
        "status": "missing",
        "category": "Disclosure",
        "page_issue": None,
    },
    {
        "id": 25,
        "name": "Flood certification",
        "mismo_type": "FLOOD_CERT",
        "pages": "—",
        "page_count": 0,
        "confidence": 0,
        "status": "missing",
        "category": "Property",
        "page_issue": None,
    },
)


# Loan-program confirmation analysis (US-3.11). Ported 1:1 from the
# demo's CONFIRMATION_ANALYSIS constant. The stub uses these verdicts
# when persisting findings: the packet's declared program id picks the
# entry, and the fields flow onto the `packets` row so the dashboard
# pill can render Confirmed / Conflict / Inconclusive without another
# round trip.
class _Confirmation(TypedDict, total=False):
    status: Literal["confirmed", "conflict", "inconclusive"]
    documents_analyzed: list[str]
    evidence: str
    suggested_program_id: str | None


CONFIRMATION_BY_PROGRAM: dict[str, _Confirmation] = {
    "conventional": {
        "status": "confirmed",
        "documents_analyzed": ["Note", "Closing Disclosure", "URLA 1003"],
        "evidence": (
            "Loan amount $385,000 is under the FHFA 2026 conforming limit of "
            "$766,550. Note references Fannie Mae servicing. No FHA case "
            "number, VA certificate, or USDA conditional commitment found in "
            "packet. Documents are consistent with the declared Conventional "
            "Conforming program."
        ),
        "suggested_program_id": None,
    },
    "jumbo": {
        "status": "conflict",
        "documents_analyzed": ["Note", "Closing Disclosure"],
        "evidence": (
            "Loan amount $385,000 is below the 2026 conforming limit of "
            "$766,550 for this county. Jumbo designation requires loan "
            "amount above conforming limits. Documents suggest Conventional "
            "Conforming instead."
        ),
        "suggested_program_id": "conventional",
    },
    "fha": {
        "status": "conflict",
        "documents_analyzed": ["Note", "URLA 1003", "Disclosure bundle"],
        "evidence": (
            "No FHA case number found in packet. URLA 1003 does not indicate "
            "FHA insurance. No FHA-specific disclosures (Amendatory Clause, "
            "Informed Consumer Choice) present. Documents suggest this is a "
            "Conventional Conforming loan."
        ),
        "suggested_program_id": "conventional",
    },
    "va": {
        "status": "conflict",
        "documents_analyzed": ["Note", "URLA 1003"],
        "evidence": (
            "No VA Certificate of Eligibility found in packet. No VA Funding "
            "Fee disclosure. URLA does not reference VA guaranty. Documents "
            "suggest Conventional Conforming."
        ),
        "suggested_program_id": "conventional",
    },
    "usda": {
        "status": "conflict",
        "documents_analyzed": ["Note", "Property Appraisal"],
        "evidence": (
            "No USDA conditional commitment in packet. Property address "
            "(Springfield, IL) is not in a USDA-eligible rural area per 2026 "
            "USDA eligibility maps. Documents suggest Conventional Conforming."
        ),
        "suggested_program_id": "conventional",
    },
    "nonqm": {
        "status": "inconclusive",
        "documents_analyzed": ["Note", "URLA 1003", "Income documentation"],
        "evidence": (
            "Standard W-2 income documentation present. No bank statement "
            "program indicators or DSCR calculations found. Packet appears "
            "to be full-doc. However, Non-QM designation depends on investor "
            "classification not deterministic from packet alone. Proceeding "
            "with declared program."
        ),
        "suggested_program_id": None,
    },
}
