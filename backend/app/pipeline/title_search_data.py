"""Deterministic canned Title Search & Abstraction findings (US-6.1).

Ported 1:1 from the `one-logikality-demo` reference (`lib/demo-data.ts`
-> `TITLE_FLAGS`, `PROPERTY_SUMMARY`) so the Title Search page reads the
same numbers end-to-end. The ECV stub writes these rows during the
`score` stage alongside the existing ECV / Compliance / Income findings.

When the real title workflow lands (MISMO title commitment / deed
extraction + chain-of-title analysis) it will replace the stub entry
point but can keep this module around as the fallback / seed.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class _MismoField(TypedDict):
    entity: str
    field: str
    value: str
    confidence: int


class _AiRec(TypedDict):
    decision: Literal["approve", "reject", "escalate"]
    confidence: int
    reasoning: str


class _Source(TypedDict):
    doc_type: str
    pages: tuple[int, ...]


class _Evidence(TypedDict):
    page: int
    snippet: str


class _CrossAppRef(TypedDict):
    app: str
    section: str
    note: str


class _TitleFlag(TypedDict):
    number: int
    severity: Literal["critical", "high", "medium", "low"]
    flag_type: str
    title: str
    description: str
    page_ref: str
    ai_note: str
    ai_rec: _AiRec
    mismo: tuple[_MismoField, ...]
    source: _Source
    cross_app: _CrossAppRef | None
    evidence: tuple[_Evidence, ...]


# 7 canned title flags — mix of severities + AI decisions so the Flags
# tab has realistic variety.
TITLE_FLAGS: tuple[_TitleFlag, ...] = (
    {
        "number": 1,
        "severity": "critical",
        "flag_type": "Unreleased Mortgage",
        "title": "Open mortgage lien from First National Bank",
        "description": (
            "Mortgage recorded 2019-03-15, Inst #2019-042871. No satisfaction of record "
            "found. Must be released or paid at closing."
        ),
        "page_ref": "p. 42, 78",
        "ai_note": (
            "This mortgage was originated in 2019 and no satisfaction or release has "
            "been recorded. The lien remains active at $312,000. Contact First National "
            "Bank's payoff department for a current payoff statement."
        ),
        "ai_rec": {
            "decision": "reject",
            "confidence": 97,
            "reasoning": "Active mortgage lien cannot be insured over. Payoff or release required.",
        },
        "mismo": (
            {"entity": "LIEN", "field": "LienType", "value": "MORTGAGE", "confidence": 97},
            {
                "entity": "LIEN",
                "field": "LienHolder",
                "value": "First National Bank",
                "confidence": 95,
            },
            {"entity": "LIEN", "field": "LienAmount", "value": "$312,000.00", "confidence": 92},
            {"entity": "LIEN", "field": "RecordingDate", "value": "2019-03-15", "confidence": 99},
            {
                "entity": "LIEN",
                "field": "InstrumentNumber",
                "value": "2019-042871",
                "confidence": 98,
            },
            {"entity": "LIEN", "field": "SatisfactionDate", "value": "NULL", "confidence": 96},
        ),
        "source": {"doc_type": "DEED_OF_TRUST", "pages": (42, 78)},
        "cross_app": {
            "app": "Compliance",
            "section": "Loan Terms",
            "note": "Lien amount cross-referenced against CD closing costs",
        },
        "evidence": (
            {
                "page": 42,
                "snippet": (
                    "DEED OF TRUST...First National Bank...amount of $312,000.00...recorded "
                    "March 15, 2019"
                ),
            },
            {
                "page": 78,
                "snippet": (
                    "No release or satisfaction of the above-described instrument has been "
                    "recorded as of the effective date"
                ),
            },
        ),
    },
    {
        "number": 2,
        "severity": "critical",
        "flag_type": "Chain of Title Gap",
        "title": "Missing link in chain of title — 2008 to 2012",
        "description": (
            "Property transferred from Johnson Trust to current owner without recorded "
            "intermediate conveyance. Gap period: 4 years."
        ),
        "page_ref": "p. 15–22",
        "ai_note": (
            "The chain of title shows a gap between the Johnson Family Trust (2008) and "
            "current owner. No recorded conveyance bridges this 4-year period. A quiet "
            "title action or affidavit may be needed."
        ),
        "ai_rec": {
            "decision": "escalate",
            "confidence": 88,
            "reasoning": (
                "Chain of title gap requires legal review. Recommend title counsel involvement."
            ),
        },
        "mismo": (
            {
                "entity": "TITLE",
                "field": "TitleVestingType",
                "value": "TRUST → INDIVIDUAL",
                "confidence": 88,
            },
            {
                "entity": "TITLE",
                "field": "TitleHolderName",
                "value": "Johnson Family Trust",
                "confidence": 91,
            },
            {"entity": "TITLE", "field": "RecordingDate", "value": "2008-06-22", "confidence": 97},
            {
                "entity": "TITLE",
                "field": "GranteeName",
                "value": "Jane A. Smith",
                "confidence": 94,
            },
        ),
        "source": {"doc_type": "WARRANTY_DEED", "pages": (15, 16, 17, 18, 19, 20, 21, 22)},
        "cross_app": None,
        "evidence": (
            {
                "page": 15,
                "snippet": (
                    "WARRANTY DEED...Johnson Family Trust, Grantor...to Jane A. Smith, "
                    "Grantee...dated June 22, 2008"
                ),
            },
            {
                "page": 19,
                "snippet": (
                    "No intermediate conveyance found between the Trust distribution and "
                    "the current deed of record"
                ),
            },
        ),
    },
    {
        "number": 3,
        "severity": "high",
        "flag_type": "Unacceptable Exception",
        "title": "Easement for utility access — non-standard terms",
        "description": (
            "Utility easement recorded in Book 1847, Page 233 contains non-standard "
            "maintenance obligations that exceed typical scope."
        ),
        "page_ref": "p. 91",
        "ai_note": (
            "The utility easement includes a non-standard clause requiring the property "
            "owner to bear 50% of repair costs. Standard utility easements do not impose "
            "cost-sharing obligations on the servient estate."
        ),
        "ai_rec": {
            "decision": "reject",
            "confidence": 82,
            "reasoning": (
                "Non-standard cost-sharing clause creates liability. "
                "Recommend ALTA 28.1 endorsement."
            ),
        },
        "mismo": (
            {
                "entity": "PROPERTY",
                "field": "EasementType",
                "value": "UTILITY_ACCESS",
                "confidence": 93,
            },
            {
                "entity": "PROPERTY",
                "field": "EasementRecordingRef",
                "value": "Book 1847, Page 233",
                "confidence": 99,
            },
            {
                "entity": "PROPERTY",
                "field": "EasementRestriction",
                "value": "Non-standard maintenance",
                "confidence": 86,
            },
        ),
        "source": {"doc_type": "TITLE_COMMITMENT", "pages": (91,)},
        "cross_app": None,
        "evidence": (
            {
                "page": 91,
                "snippet": (
                    "Easement for utility access...property owner shall bear fifty percent "
                    "(50%) of repair and maintenance costs"
                ),
            },
        ),
    },
    {
        "number": 4,
        "severity": "high",
        "flag_type": "Name Discrepancy",
        "title": "Vesting name mismatch — Smith vs. Smyth",
        "description": (
            "Deed shows grantee as 'Jane Smyth' but commitment shows insured as 'Jane "
            "Smith'. Corrective deed or affidavit required."
        ),
        "page_ref": "p. 3, 67",
        "ai_note": (
            "The warranty deed records grantee as 'Jane Smyth' while the commitment shows "
            "'Jane Smith'. The borrower's W-2 and driver's license both show 'Jane Smith'. "
            "A corrective deed would resolve this."
        ),
        "ai_rec": {
            "decision": "approve",
            "confidence": 91,
            "reasoning": (
                "Likely clerical error. Approve with condition for corrective deed before closing."
            ),
        },
        "mismo": (
            {"entity": "TITLE", "field": "GranteeName", "value": "Jane Smyth", "confidence": 94},
            {"entity": "TITLE", "field": "InsuredName", "value": "Jane Smith", "confidence": 98},
        ),
        "source": {"doc_type": "WARRANTY_DEED + TITLE_COMMITMENT", "pages": (3, 67)},
        "cross_app": {
            "app": "ECV",
            "section": "Borrower Identity",
            "note": "Borrower identity section scored 80% — marital status also flagged",
        },
        "evidence": (
            {"page": 67, "snippet": "...convey and warrant to Jane Smyth, an unmarried person..."},
            {"page": 3, "snippet": "Proposed Insured: Jane Smith"},
        ),
    },
    {
        "number": 5,
        "severity": "medium",
        "flag_type": "Missing Endorsement",
        "title": "ALTA 9.0 (Restrictions) endorsement not included",
        "description": (
            "Title commitment references restrictive covenants in Schedule B-II but ALTA "
            "9.0 endorsement is not listed in Schedule A."
        ),
        "page_ref": "p. 5",
        "ai_note": (
            "Schedule B-II lists restrictive covenants but the ALTA 9.0 endorsement is not "
            "in Schedule A. This endorsement provides coverage against existing violations "
            "of those covenants."
        ),
        "ai_rec": {
            "decision": "approve",
            "confidence": 94,
            "reasoning": (
                "Standard endorsement request. No known violations. Add ALTA 9.0 to Schedule A."
            ),
        },
        "mismo": (
            {
                "entity": "TITLE",
                "field": "EndorsementType",
                "value": "ALTA_9_0",
                "confidence": 0,
            },
            {
                "entity": "PROPERTY",
                "field": "RestrictiveCovenant",
                "value": "Present — Schedule B-II",
                "confidence": 91,
            },
        ),
        "source": {"doc_type": "TITLE_COMMITMENT", "pages": (5,)},
        "cross_app": None,
        "evidence": (
            {
                "page": 5,
                "snippet": (
                    "Schedule B-II, Exception 4: Restrictive covenants "
                    "recorded in Book 920, Page 114"
                ),
            },
        ),
    },
    {
        "number": 6,
        "severity": "medium",
        "flag_type": "Tax Issue",
        "title": "Delinquent property taxes — 2024 second installment",
        "description": (
            "County records show $2,847.33 unpaid for 2024 second installment. Must be "
            "paid or escrowed at closing."
        ),
        "page_ref": "p. 103",
        "ai_note": (
            "Sangamon County records show $2,847.33 unpaid for 2024 second installment. "
            "Delinquent taxes constitute a superior lien. Can be resolved by payment from "
            "closing proceeds."
        ),
        "ai_rec": {
            "decision": "approve",
            "confidence": 96,
            "reasoning": "Routine tax delinquency. Standard practice to pay from closing proceeds.",
        },
        "mismo": (
            {"entity": "PROPERTY", "field": "TaxStatus", "value": "DELINQUENT", "confidence": 97},
            {"entity": "PROPERTY", "field": "TaxAmount", "value": "$2,847.33", "confidence": 95},
            {"entity": "PROPERTY", "field": "TaxYear", "value": "2024", "confidence": 99},
            {"entity": "PROPERTY", "field": "TaxInstallment", "value": "Second", "confidence": 98},
        ),
        "source": {"doc_type": "TAX_CERTIFICATE", "pages": (103,)},
        "cross_app": {
            "app": "Compliance",
            "section": "Cross-Doc Reconciliation",
            "note": "Tax amount referenced in escrow calculation",
        },
        "evidence": (
            {
                "page": 103,
                "snippet": (
                    "2024 Second Installment: $2,847.33 — STATUS: UNPAID — Due Date: "
                    "September 1, 2024"
                ),
            },
        ),
    },
    {
        "number": 7,
        "severity": "low",
        "flag_type": "Vesting Issue",
        "title": "Tenancy type not specified in current deed",
        "description": (
            "Deed records ownership but does not specify joint tenancy, tenancy in common, "
            "or other form. Clarification recommended."
        ),
        "page_ref": "p. 67",
        "ai_note": (
            "The deed conveys to 'Jane A. Smith' without specifying tenancy. Since she is "
            "the sole borrower, Illinois defaults to tenancy in severalty. Recommend "
            "specifying in the new deed."
        ),
        "ai_rec": {
            "decision": "approve",
            "confidence": 93,
            "reasoning": "Sole owner — Illinois defaults to severalty. No immediate risk.",
        },
        "mismo": (
            {
                "entity": "TITLE",
                "field": "TitleVestingType",
                "value": "NOT_SPECIFIED",
                "confidence": 89,
            },
            {
                "entity": "TITLE",
                "field": "TitleHolderName",
                "value": "Jane A. Smith",
                "confidence": 96,
            },
        ),
        "source": {"doc_type": "WARRANTY_DEED", "pages": (67,)},
        "cross_app": None,
        "evidence": ({"page": 67, "snippet": "...convey and warrant to Jane A. Smith..."},),
    },
)


# Full PROPERTY_SUMMARY payload — ported verbatim. Stored as a single
# JSONB document (see `models.TitleProperty`) because the shape is
# consumed as a nested structure by the Results tab.
PROPERTY_SUMMARY: dict[str, Any] = {
    "property_identification": {
        "address": "742 Evergreen Terrace, Springfield, IL 62704",
        "county": "Sangamon County",
        "state": "Illinois",
        "parcel_number": "14-28-301-017",
        "legal_description": (
            "Lot 17, Block 3, of Evergreen Terrace Subdivision, being a part of the "
            "Northeast Quarter of Section 28, Township 16 North, Range 5 West of the "
            "Third Principal Meridian, Sangamon County, Illinois."
        ),
        "zip_code": "62704",
    },
    "physical_attributes": {
        "property_type": "Single Family Residence",
        "year_built": 1962,
        "living_area_sqft": 2340,
        "stories": 2,
        "bedrooms": 4,
        "bathrooms": 2.5,
        "basement": "Full, unfinished",
        "garage": "2-car attached",
    },
    "lot_and_land": {
        "lot_size_sqft": 11250,
        "lot_size_acres": 0.258,
        "zoning": "R-1 Single Family",
        "flood_zone": "X (not in flood zone)",
        "subdivision": "Evergreen Terrace",
        "school_district": "Springfield Public Schools District 186",
    },
    "current_ownership": {
        "vested_in": "Jane A. Smith",
        "vesting_type": "Fee Simple",
        "ownership_form": "Sole Ownership",
        "acquired_date": "2012-06-15",
        "acquisition_deed": "Warranty Deed, Inst #2012-048721",
    },
    "chain_of_title": [
        {
            "deed_type": "Warranty Deed",
            "recording_date": "1998-11-02",
            "grantor": "Original Plat LLC",
            "grantee": "Robert Williams",
            "consideration": 142500,
            "recording_ref": "1998-089412",
        },
        {
            "deed_type": "Grant Deed",
            "recording_date": "2008-06-22",
            "grantor": "Robert Williams Estate",
            "grantee": "Johnson Family Trust",
            "consideration": 195000,
            "recording_ref": "2008-031244",
        },
        {
            "deed_type": "Warranty Deed",
            "recording_date": "2012-06-15",
            "grantor": "Johnson Family Trust",
            "grantee": "Jane A. Smith",
            "consideration": 248000,
            "recording_ref": "2012-048721",
        },
    ],
    "mortgages": [
        {
            "lender": "First National Bank",
            "amount": "$312,000",
            "borrower": "Jane A. Smith",
            "recording_date": "2019-03-15",
            "recording_ref": "2019-042871",
            "status": "active",
        },
    ],
    "liens": [
        {
            "lien_type": "Property Tax Lien",
            "amount": "$2,847.22",
            "recording_date": "2024-09-01",
            "recording_ref": "TL-2024-4421",
            "description": "Delinquent 2023 property taxes — second installment unpaid",
            "status": "unreleased",
        },
    ],
    "easements": [
        {
            "type": "Utility Easement",
            "holder": "Springfield Power Company",
            "recording_date": "2001-04-10",
            "recording_ref": "Book 1847, Page 233",
            "description": (
                "Non-standard 50% maintenance cost sharing clause — unusual for "
                "residential utility easement"
            ),
        },
    ],
    "restrictions": [
        {
            "type": "Restrictive Covenants",
            "holder": "Evergreen Terrace HOA",
            "recording_date": "1996-01-15",
            "recording_ref": "Book 920, Page 114",
            "description": (
                "Residential-only use, architectural approval required for exterior modifications"
            ),
        },
    ],
    "taxes": {
        "annual_taxes": "$5,694.40",
        "tax_year": 2024,
        "assessed_value": "$186,000",
        "market_value": "$410,000",
        "status": "Delinquent — $2,847.22 past due",
    },
    "title_insurance": {
        "commitment_number": "TC-2024-08-4521",
        "effective_date": "2026-03-28",
        "issued_by": "First American Title",
        "proposed_insured": (
            "Jane A. Smith (Owner's Policy); First National Bank (Lender's Policy)"
        ),
        "liability_amount": "$385,000",
    },
}
