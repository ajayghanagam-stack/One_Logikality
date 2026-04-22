"""Deterministic canned Compliance findings (US-6.3).

Ported from the `one-logikality-demo` reference and extended to match the
TI-parity `ComplianceOutput` TypeScript interface exactly: every check
carries a `check_type` bucket key mapping it to one of the six
`categories` arrays (disclosureTiming / feeTolerances / requiredDisclosures
/ programSpecific / fairLending / stateSpecific), a ruleId, a regulatory
citation, a severity, and a category-specific `details` JSONB payload
(timing deadlines, disclosure signatures, etc.). Fee-tolerance rows gain
numeric LE/CD amounts, dates, and optional cure amounts.

Packet-level metadata (applied framework, applied rules, evidence trace,
confidence) lives alongside the array-shaped seeds and is persisted by
the pipeline stub into the new `compliance_packet_metadata` and
`compliance_findings` tables introduced in migration 0015.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, TypedDict


class _MismoField(TypedDict):
    entity: str
    field: str
    value: str
    confidence: int


class _ComplianceCheck(TypedDict):
    code: str
    category: str
    rule: str
    status: Literal["pass", "fail", "warn", "n/a"]
    detail: str
    ai_note: str | None
    mismo: tuple[_MismoField, ...]
    check_type: Literal[
        "disclosure_timing",
        "fee_tolerance",
        "required_disclosure",
        "program_specific",
        "fair_lending",
        "state_specific",
    ]
    rule_id: str
    citation: str
    severity: Literal["critical", "warning", "info"]
    details: dict[str, object]


class _ToleranceRow(TypedDict):
    bucket: str
    le: str
    cd: str
    diff: str
    pct: str
    status: Literal["pass", "fail", "warn"]
    # TI-parity additions.
    rule_id: str
    citation: str
    fee_name: str
    fee_category: Literal["zero_tolerance", "ten_percent", "no_tolerance"]
    le_date: str  # ISO yyyy-mm-dd
    cd_date: str
    severity: Literal["critical", "warning", "info"]
    le_amount_num: Decimal
    cd_amount_num: Decimal
    cure_amount: Decimal | None


class _ComplianceFinding(TypedDict):
    finding_id: str
    severity: Literal["critical", "warning", "info"]
    category: str
    rule_id: str
    description: str
    impact: str
    recommendation: str
    curative: dict[str, object] | None
    regulatory_citation: str
    affected_parties: tuple[str, ...]
    mismo_refs: tuple[str, ...]


class _EvidenceTrace(TypedDict):
    document_id: str
    page: int
    mismo_path: str
    snippet: str


class _AppliedFramework(TypedDict):
    regulatory: str
    disclosure_set: str
    program_overlays: tuple[str, ...]


class _AppliedRules(TypedDict):
    program_id: str
    rule_set_version: str
    state_code: str


# ---------------------------------------------------------------------------
# 10 canned compliance checks — C-01 through C-10. Mix of pass / fail /
# warn / n/a statuses so the Violations tab has real data to classify.
# Every row now carries `check_type`, `rule_id`, `citation`, `severity`,
# and a category-specific `details` payload per TI-parity interface.
# ---------------------------------------------------------------------------

COMPLIANCE_CHECKS: tuple[_ComplianceCheck, ...] = (
    {
        "code": "C-01",
        "category": "TRID — Loan Estimate delivery",
        "rule": "LE must be delivered within 3 business days of application",
        "status": "pass",
        "detail": (
            "LE delivered Day 2 of application. Application date: 2026-02-14. "
            "LE issued: 2026-02-16."
        ),
        "ai_note": None,
        "mismo": (
            {
                "entity": "LOAN_ESTIMATE",
                "field": "IssuedDate",
                "value": "2026-02-16",
                "confidence": 96,
            },
            {
                "entity": "APPLICATION",
                "field": "ReceivedDate",
                "value": "2026-02-14",
                "confidence": 99,
            },
        ),
        "check_type": "disclosure_timing",
        "rule_id": "TRID.LE.3_day_delivery",
        "citation": "12 CFR 1026.19(e)(1)(iii)",
        "severity": "info",
        "details": {
            "required_disclosure": "Loan Estimate",
            "required_deadline": "within 3 business days of application",
            "actual_delivery_date": "2026-02-16",
            "method": "email",
            "receipt_date": "2026-02-16",
            "days_elapsed": 2,
        },
    },
    {
        "code": "C-02",
        "category": "TRID — Closing Disclosure delivery",
        "rule": "CD must be delivered at least 3 business days before closing",
        "status": "fail",
        "detail": (
            "CD dated 2026-03-25. Closing date: 2026-03-27. Only 2 business days — TRID violation."
        ),
        "ai_note": (
            "The Closing Disclosure was delivered only 2 business days before closing, "
            "violating the TRID 3-day rule. The closing must be postponed or a corrected "
            "CD issued with a new 3-day waiting period."
        ),
        "mismo": (
            {
                "entity": "CLOSING_DISCLOSURE",
                "field": "IssuedDate",
                "value": "2026-03-25",
                "confidence": 62,
            },
            {
                "entity": "CLOSING",
                "field": "ClosingDate",
                "value": "2026-03-27",
                "confidence": 94,
            },
        ),
        "check_type": "disclosure_timing",
        "rule_id": "TRID.CD.3_day_waiting_period",
        "citation": "12 CFR 1026.19(f)(1)(ii)",
        "severity": "critical",
        "details": {
            "required_disclosure": "Closing Disclosure",
            "required_deadline": "at least 3 business days before consummation",
            "actual_delivery_date": "2026-03-25",
            "method": "email",
            "receipt_date": "2026-03-25",
            "days_elapsed": 2,
        },
    },
    {
        "code": "C-03",
        "category": "TRID — Zero tolerance fees",
        "rule": "Fees in zero-tolerance bucket must not increase from LE to CD",
        "status": "pass",
        "detail": (
            "Transfer taxes: LE $4,200.00, CD $4,200.00. Difference: $0.00. Within tolerance."
        ),
        "ai_note": None,
        "mismo": (
            {
                "entity": "TOLERANCE",
                "field": "ZeroToleranceFees_LE",
                "value": "$4,200.00",
                "confidence": 97,
            },
            {
                "entity": "TOLERANCE",
                "field": "ZeroToleranceFees_CD",
                "value": "$4,200.00",
                "confidence": 98,
            },
        ),
        "check_type": "fee_tolerance",
        "rule_id": "TRID.zero_tolerance.transfer_taxes",
        "citation": "12 CFR 1026.19(e)(3)(i)",
        "severity": "info",
        "details": {
            "fee_category": "zero_tolerance",
            "fee_name": "Transfer taxes",
            "le_amount": 4200.00,
            "cd_amount": 4200.00,
            "difference": 0.00,
        },
    },
    {
        "code": "C-04",
        "category": "TRID — 10% tolerance fees",
        "rule": "Aggregate fees in 10% bucket must not exceed 10% increase",
        "status": "warn",
        "detail": (
            "Recording fees: LE $450.00, CD $488.00. Increase: 8.4%. "
            "Within tolerance but approaching limit."
        ),
        "ai_note": (
            "This item is within tolerance but approaching the limit. "
            "Monitor closely if any change requests or amendments are made before closing."
        ),
        "mismo": (
            {
                "entity": "TOLERANCE",
                "field": "TenPercentFees_LE",
                "value": "$450.00",
                "confidence": 95,
            },
            {
                "entity": "TOLERANCE",
                "field": "TenPercentFees_CD",
                "value": "$488.00",
                "confidence": 96,
            },
        ),
        "check_type": "fee_tolerance",
        "rule_id": "TRID.ten_percent.recording_fees",
        "citation": "12 CFR 1026.19(e)(3)(ii)",
        "severity": "warning",
        "details": {
            "fee_category": "ten_percent",
            "fee_name": "Recording fees",
            "le_amount": 450.00,
            "cd_amount": 488.00,
            "difference": 38.00,
        },
    },
    {
        "code": "C-05",
        "category": "RESPA — Affiliated business disclosure",
        "rule": "AfBA disclosure must be provided when referring to affiliated services",
        "status": "pass",
        "detail": (
            "Affiliated Business Arrangement disclosure signed and dated. "
            "Title company is affiliated entity."
        ),
        "ai_note": None,
        "mismo": (
            {
                "entity": "DISCLOSURE",
                "field": "AfBAProvided",
                "value": "true",
                "confidence": 91,
            },
        ),
        "check_type": "required_disclosure",
        "rule_id": "RESPA.AfBA",
        "citation": "12 CFR 1024.15",
        "severity": "info",
        "details": {
            "disclosure_name": "Affiliated Business Arrangement",
            "required": True,
            "found": True,
            "document_id": "DOC-AFBA",
            "page_ref": 1,
            "signed_by_borrower": True,
        },
    },
    {
        "code": "C-06",
        "category": "ECOA — Adverse action",
        "rule": "Equal credit opportunity compliance — no prohibited factors in decision",
        "status": "pass",
        "detail": "No prohibited factors found in underwriting notes or conditions.",
        "ai_note": None,
        "mismo": (
            {
                "entity": "COMPLIANCE",
                "field": "ECOACompliant",
                "value": "true",
                "confidence": 88,
            },
        ),
        "check_type": "fair_lending",
        "rule_id": "ECOA.prohibited_factors",
        "citation": "12 CFR 1002.4",
        "severity": "info",
        "details": {
            "factors_checked": [
                "race",
                "color",
                "religion",
                "national_origin",
                "sex",
                "marital_status",
                "age",
            ],
            "flagged": False,
        },
    },
    {
        "code": "C-07",
        "category": "Right of rescission",
        "rule": "For refinances, 3-day right of rescission notice must be provided",
        "status": "n/a",
        "detail": "This is a purchase transaction. Right of rescission does not apply.",
        "ai_note": None,
        "mismo": (),
        "check_type": "required_disclosure",
        "rule_id": "TILA.right_of_rescission",
        "citation": "12 CFR 1026.23",
        "severity": "info",
        "details": {
            "disclosure_name": "Right of Rescission",
            "required": False,
            "reason": "purchase transaction (not a refinance)",
        },
    },
    {
        "code": "C-08",
        "category": "State disclosure — Illinois",
        "rule": "IL-specific disclosures must be present (Radon, Lead Paint if pre-1978)",
        "status": "fail",
        "detail": (
            "Lead paint disclosure found. Radon disclosure NOT found in packet. "
            "Property built 1962 — both required."
        ),
        "ai_note": (
            "Illinois requires both Lead Paint and Radon disclosures for pre-1978 "
            "properties. The Radon disclosure must be obtained from the seller "
            "before closing."
        ),
        "mismo": (
            {
                "entity": "DISCLOSURE",
                "field": "LeadPaintDisclosure",
                "value": "Present",
                "confidence": 94,
            },
            {
                "entity": "DISCLOSURE",
                "field": "RadonDisclosure",
                "value": "NOT_FOUND",
                "confidence": 0,
            },
        ),
        "check_type": "state_specific",
        "rule_id": "IL.radon_disclosure",
        "citation": "420 ILCS 46/10",
        "severity": "critical",
        "details": {
            "state_code": "IL",
            "disclosure_name": "Illinois Radon Awareness",
            "required": True,
            "found": False,
            "reason_required": "property constructed before 1978",
        },
    },
    {
        "code": "C-09",
        "category": "HMDA — Data accuracy",
        "rule": "HMDA-reportable fields must be accurately captured",
        "status": "pass",
        "detail": "All HMDA fields present and consistent.",
        "ai_note": None,
        "mismo": (
            {
                "entity": "HMDA",
                "field": "DataComplete",
                "value": "true",
                "confidence": 93,
            },
        ),
        "check_type": "fair_lending",
        "rule_id": "HMDA.data_completeness",
        "citation": "12 CFR 1003.4",
        "severity": "info",
        "details": {
            "fields_checked": 48,
            "fields_complete": 48,
        },
    },
    {
        "code": "C-10",
        "category": "Escrow account",
        "rule": "Initial escrow account disclosure must be provided at closing",
        "status": "pass",
        "detail": "Escrow disclosure present. Monthly escrow: $487.50.",
        "ai_note": None,
        "mismo": (
            {
                "entity": "ESCROW",
                "field": "MonthlyAmount",
                "value": "$487.50",
                "confidence": 96,
            },
        ),
        "check_type": "required_disclosure",
        "rule_id": "RESPA.initial_escrow_statement",
        "citation": "12 CFR 1024.17(g)",
        "severity": "info",
        "details": {
            "disclosure_name": "Initial Escrow Account Statement",
            "required": True,
            "found": True,
            "document_id": "DOC-ESCROW",
            "page_ref": 1,
            "signed_by_borrower": True,
        },
    },
)


# Three TRID tolerance buckets per 12 CFR 1026.19(e)(3). Rendered as a
# table on the Fee Tolerances tab; `sort_order` preserves the demo order
# regardless of insert timing.
TOLERANCE_TABLE: tuple[_ToleranceRow, ...] = (
    {
        "bucket": "Zero tolerance (0%)",
        "le": "$4,200.00",
        "cd": "$4,200.00",
        "diff": "$0.00",
        "pct": "0.0%",
        "status": "pass",
        "rule_id": "TRID.zero_tolerance.transfer_taxes",
        "citation": "12 CFR 1026.19(e)(3)(i)",
        "fee_name": "Transfer taxes",
        "fee_category": "zero_tolerance",
        "le_date": "2026-02-16",
        "cd_date": "2026-03-25",
        "severity": "info",
        "le_amount_num": Decimal("4200.00"),
        "cd_amount_num": Decimal("4200.00"),
        "cure_amount": None,
    },
    {
        "bucket": "10% tolerance",
        "le": "$450.00",
        "cd": "$488.00",
        "diff": "$38.00",
        "pct": "8.4%",
        "status": "warn",
        "rule_id": "TRID.ten_percent.recording_fees",
        "citation": "12 CFR 1026.19(e)(3)(ii)",
        "fee_name": "Recording fees",
        "fee_category": "ten_percent",
        "le_date": "2026-02-16",
        "cd_date": "2026-03-25",
        "severity": "warning",
        "le_amount_num": Decimal("450.00"),
        "cd_amount_num": Decimal("488.00"),
        "cure_amount": None,
    },
    {
        "bucket": "Unlimited tolerance",
        "le": "$1,250.00",
        "cd": "$1,380.00",
        "diff": "$130.00",
        "pct": "10.4%",
        "status": "pass",
        "rule_id": "TRID.no_tolerance.owner_title_insurance",
        "citation": "12 CFR 1026.19(e)(3)(iii)",
        "fee_name": "Owner's title insurance",
        "fee_category": "no_tolerance",
        "le_date": "2026-02-16",
        "cd_date": "2026-03-25",
        "severity": "info",
        "le_amount_num": Decimal("1250.00"),
        "cd_amount_num": Decimal("1380.00"),
        "cure_amount": None,
    },
)


# ---------------------------------------------------------------------------
# Packet-level metadata: applied framework, applied rules, findings,
# evidence trace, and overall confidence.
# ---------------------------------------------------------------------------

APPLIED_FRAMEWORK: _AppliedFramework = {
    "regulatory": "CFPB 2026 + HUD",
    "disclosure_set": "TRID + Federal + State (IL)",
    "program_overlays": (),
}

APPLIED_RULES: _AppliedRules = {
    "program_id": "conventional",
    "rule_set_version": "2026-01",
    "state_code": "IL",
}


COMPLIANCE_FINDINGS: tuple[_ComplianceFinding, ...] = (
    {
        "finding_id": "CF-01",
        "severity": "critical",
        "category": "disclosure_timing",
        "rule_id": "TRID.CD.3_day_waiting_period",
        "description": (
            "Closing Disclosure delivered 2 business days before closing — "
            "TRID requires a minimum 3-business-day waiting period."
        ),
        "impact": (
            "Closing cannot lawfully proceed. Either postpone closing or "
            "re-issue a corrected CD and restart the 3-day count."
        ),
        "recommendation": (
            "Postpone closing to 2026-03-28 at earliest, or re-issue CD "
            "on 2026-03-25 with new 3-day window."
        ),
        "curative": {
            "action": "redisclose",
            "deadline": "before new closing date",
        },
        "regulatory_citation": "12 CFR 1026.19(f)(1)(ii)",
        "affected_parties": ("borrower", "co-borrower", "lender"),
        "mismo_refs": ("CLOSING_DISCLOSURE.IssuedDate", "CLOSING.ClosingDate"),
    },
    {
        "finding_id": "CF-02",
        "severity": "warning",
        "category": "fee_tolerance",
        "rule_id": "TRID.ten_percent.recording_fees",
        "description": (
            "Recording fees up 8.4% from LE to CD — within the 10% bucket "
            "tolerance but approaching the limit."
        ),
        "impact": (
            "No cure required at current variance. Any further increase "
            "before consummation would push this bucket over tolerance."
        ),
        "recommendation": (
            "Monitor for additional change requests before closing; freeze "
            "recording-fee line items if the buffer tightens."
        ),
        "curative": None,
        "regulatory_citation": "12 CFR 1026.19(e)(3)(ii)",
        "affected_parties": ("borrower",),
        "mismo_refs": ("TOLERANCE.TenPercentFees_LE", "TOLERANCE.TenPercentFees_CD"),
    },
    {
        "finding_id": "CF-03",
        "severity": "critical",
        "category": "state_specific",
        "rule_id": "IL.radon_disclosure",
        "description": (
            "Illinois Radon Awareness disclosure missing from the packet. "
            "Property built 1962 — disclosure is mandatory."
        ),
        "impact": (
            "Non-compliance with IL state law. Closing may be delayed "
            "until seller provides the Radon disclosure."
        ),
        "recommendation": (
            "Obtain signed Radon disclosure from seller before closing. "
            "Re-upload into packet and re-run compliance."
        ),
        "curative": {
            "action": "obtain_signature",
            "recipient": "seller",
            "deadline": "before closing",
        },
        "regulatory_citation": "420 ILCS 46/10",
        "affected_parties": ("seller", "borrower"),
        "mismo_refs": ("DISCLOSURE.RadonDisclosure",),
    },
)


COMPLIANCE_EVIDENCE: tuple[_EvidenceTrace, ...] = (
    {
        "document_id": "DOC-LE",
        "page": 1,
        "mismo_path": "Loan.Disclosures.LoanEstimate.IssuedDate",
        "snippet": "Loan Estimate issued: 2026-02-16",
    },
    {
        "document_id": "DOC-CD",
        "page": 1,
        "mismo_path": "Loan.Disclosures.ClosingDisclosure.IssuedDate",
        "snippet": "Closing Disclosure issued: 2026-03-25",
    },
    {
        "document_id": "DOC-CD",
        "page": 4,
        "mismo_path": ("Loan.Closing.ClosingInformation.ClosingDate"),
        "snippet": "Closing date: 2026-03-27",
    },
    {
        "document_id": "DOC-AFBA",
        "page": 1,
        "mismo_path": "Loan.Disclosures.AffiliatedBusinessArrangement.Provided",
        "snippet": "Signed by borrower on 2026-02-14",
    },
)


OVERALL_CONFIDENCE: int = 91
