"""Deterministic canned Income Calculation findings (US-6.4).

Ported from the `one-logikality-demo` reference and extended to match the
TI-parity `IncomeCalculationOutput` TypeScript interface exactly:
per-borrower employment / non-employment income, stated-vs-verified
variance, VOE metadata, MISMO 3.6 field paths, trending method per
source, and packet-level findings / evidence / applied-rules / optional
VA residual-income / overall confidence.

The pipeline stub writes the canned rows during the `score` stage so
the Income Calculation page can hydrate from server state the moment
processing completes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, TypedDict


class _MismoField(TypedDict):
    entity: str
    field: str
    value: str
    confidence: int


class _Trending(TypedDict):
    amount: Decimal
    method: Literal["averaged", "current"]
    trending: Literal["increasing", "stable", "declining"]


class _Bonus(TypedDict):
    amount: Decimal
    method: Literal["averaged", "current"]


class _Voe(TypedDict):
    type: Literal["written", "verbal", "the_work_number", "none"]
    date: str


class _MismoPaths(TypedDict):
    employer_path: str
    income_path: str


class _IncomeSource(TypedDict):
    code: str
    source_name: str
    employer: str | None
    position: str | None
    income_type: str
    monthly: Decimal
    annual: Decimal
    trend: Literal["stable", "increasing", "decreasing"]
    years: Decimal
    confidence: int
    ai_note: str
    mismo: tuple[_MismoField, ...]
    docs: tuple[str, ...]
    # TI-parity additions.
    borrower_id: str
    borrower_name: str
    category: Literal["employment", "non_employment"]
    employment_type: Literal["w2", "self_employed", "1099", "military"] | None
    start_date: str | None  # ISO yyyy-mm-dd
    tenure_years: int | None
    tenure_months: int | None
    base_salary: Decimal | None
    overtime: _Trending | None
    bonus: _Bonus | None
    commission: _Bonus | None
    total_qualifying: Decimal
    voe: _Voe | None
    mismo_paths: _MismoPaths | None
    stated_monthly: Decimal
    verified_monthly: Decimal


class _DtiItem(TypedDict):
    description: str
    monthly: Decimal


class _IncomeFinding(TypedDict):
    finding_id: str
    severity: Literal["critical", "review", "info"]
    category: Literal[
        "missing_doc",
        "variance",
        "trending_concern",
        "dti_exceeded",
        "incomplete_verification",
    ]
    description: str
    recommendation: str
    affected_sources: tuple[str, ...]
    mismo_refs: tuple[str, ...]


class _EvidenceTrace(TypedDict):
    document_id: str
    page: int
    mismo_path: str
    snippet: str


class _AppliedRules(TypedDict):
    program_id: str
    dti_limit: float
    guidelines: str
    trending_method: Literal["averaged", "declining"]
    residual_income_required: bool


class _ResidualIncome(TypedDict):
    net_monthly_income: Decimal
    total_obligations: Decimal
    residual: Decimal
    regional_table: str
    required_residual: Decimal
    meets_requirement: bool


# ---------------------------------------------------------------------------
# 4 canned income sources — I-01 through I-04. Mix of W-2 base,
# overtime, bonus, and rental so the sources tab has realistic variety.
# All four belong to the same borrower (borrower_1) — the demo seeds a
# single-borrower packet, matching the reference implementation.
# ---------------------------------------------------------------------------

PRIMARY_BORROWER_ID = "borrower_1"
PRIMARY_BORROWER_NAME = "Ethan M. Caldwell"


INCOME_SOURCES: tuple[_IncomeSource, ...] = (
    {
        "code": "I-01",
        "source_name": "Base employment",
        "employer": "Midwest Engineering Corp",
        "position": "Senior Project Manager",
        "income_type": "W-2",
        "monthly": Decimal("9366.67"),
        "annual": Decimal("112400.00"),
        "trend": "stable",
        "years": Decimal("6.2"),
        "confidence": 96,
        "ai_note": (
            "Base employment income verified across W-2 (2024, 2025) and current "
            "paystub. Borrower has been with Midwest Engineering Corp for 6.2 years "
            "— well above the 2-year Fannie Mae requirement. Income is stable and "
            "fully qualifying."
        ),
        "mismo": (
            {
                "entity": "EMPLOYMENT",
                "field": "EmployerName",
                "value": "Midwest Engineering Corp",
                "confidence": 97,
            },
            {
                "entity": "EMPLOYMENT",
                "field": "PositionTitle",
                "value": "Senior Project Manager",
                "confidence": 94,
            },
            {
                "entity": "INCOME",
                "field": "BaseMonthlyIncome",
                "value": "$9,366.67",
                "confidence": 96,
            },
        ),
        "docs": ("W-2 (2025)", "W-2 (2024)", "Paystub (Mar 2026)"),
        "borrower_id": PRIMARY_BORROWER_ID,
        "borrower_name": PRIMARY_BORROWER_NAME,
        "category": "employment",
        "employment_type": "w2",
        "start_date": "2020-01-06",
        "tenure_years": 6,
        "tenure_months": 2,
        "base_salary": Decimal("9366.67"),
        "overtime": None,
        "bonus": None,
        "commission": None,
        "total_qualifying": Decimal("9366.67"),
        "voe": {"type": "written", "date": "2026-02-18"},
        "mismo_paths": {
            "employer_path": "Loan.Borrowers.Borrower[0].Employers.Employer[0]",
            "income_path": (
                "Loan.Borrowers.Borrower[0].Employers.Employer[0]"
                ".CurrentIncomeItems.CurrentIncomeItem[0]"
            ),
        },
        "stated_monthly": Decimal("9366.67"),
        "verified_monthly": Decimal("9366.67"),
    },
    {
        "code": "I-02",
        "source_name": "Overtime",
        "employer": "Midwest Engineering Corp",
        "position": None,
        "income_type": "W-2 / Paystub",
        "monthly": Decimal("780.00"),
        "annual": Decimal("9360.00"),
        "trend": "increasing",
        "years": Decimal("3.0"),
        "confidence": 88,
        "ai_note": (
            "Overtime income shows an increasing trend over 3 years. Per Fannie "
            "Mae B3-3.1-01, overtime can be used as qualifying income when the "
            "borrower has a 2-year history. The upward trend supports full "
            "inclusion."
        ),
        "mismo": (
            {
                "entity": "INCOME",
                "field": "OvertimeMonthly",
                "value": "$780.00",
                "confidence": 88,
            },
            {
                "entity": "INCOME",
                "field": "OvertimeTrend",
                "value": "INCREASING",
                "confidence": 82,
            },
        ),
        "docs": ("W-2 (2025)", "W-2 (2024)", "W-2 (2023)", "Paystub YTD"),
        "borrower_id": PRIMARY_BORROWER_ID,
        "borrower_name": PRIMARY_BORROWER_NAME,
        "category": "employment",
        "employment_type": "w2",
        "start_date": "2023-01-01",
        "tenure_years": 3,
        "tenure_months": 0,
        "base_salary": None,
        "overtime": {
            "amount": Decimal("780.00"),
            "method": "averaged",
            "trending": "increasing",
        },
        "bonus": None,
        "commission": None,
        "total_qualifying": Decimal("780.00"),
        "voe": {"type": "written", "date": "2026-02-18"},
        "mismo_paths": {
            "employer_path": "Loan.Borrowers.Borrower[0].Employers.Employer[0]",
            "income_path": (
                "Loan.Borrowers.Borrower[0].Employers.Employer[0]"
                ".CurrentIncomeItems.CurrentIncomeItem[1]"
            ),
        },
        "stated_monthly": Decimal("750.00"),
        "verified_monthly": Decimal("780.00"),
    },
    {
        "code": "I-03",
        "source_name": "Bonus income",
        "employer": "Midwest Engineering Corp",
        "position": None,
        "income_type": "W-2",
        "monthly": Decimal("416.67"),
        "annual": Decimal("5000.00"),
        "trend": "stable",
        "years": Decimal("2.0"),
        "confidence": 84,
        "ai_note": (
            "Bonus income documented for 2 years per W-2s. Fannie Mae requires a "
            "2-year history for bonus income. The $5,000 annual bonus is "
            "consistent across both years."
        ),
        "mismo": (
            {
                "entity": "INCOME",
                "field": "BonusMonthly",
                "value": "$416.67",
                "confidence": 84,
            },
            {
                "entity": "INCOME",
                "field": "BonusHistory",
                "value": "2yr documented",
                "confidence": 90,
            },
        ),
        "docs": ("W-2 (2025)", "W-2 (2024)"),
        "borrower_id": PRIMARY_BORROWER_ID,
        "borrower_name": PRIMARY_BORROWER_NAME,
        "category": "employment",
        "employment_type": "w2",
        "start_date": "2024-01-01",
        "tenure_years": 2,
        "tenure_months": 0,
        "base_salary": None,
        "overtime": None,
        "bonus": {"amount": Decimal("416.67"), "method": "averaged"},
        "commission": None,
        "total_qualifying": Decimal("416.67"),
        "voe": {"type": "written", "date": "2026-02-18"},
        "mismo_paths": {
            "employer_path": "Loan.Borrowers.Borrower[0].Employers.Employer[0]",
            "income_path": (
                "Loan.Borrowers.Borrower[0].Employers.Employer[0]"
                ".CurrentIncomeItems.CurrentIncomeItem[2]"
            ),
        },
        "stated_monthly": Decimal("416.67"),
        "verified_monthly": Decimal("416.67"),
    },
    {
        "code": "I-04",
        "source_name": "Rental income",
        "employer": None,
        "position": "123 Oak St, Unit B",
        "income_type": "1040 Sch E",
        "monthly": Decimal("650.00"),
        "annual": Decimal("7800.00"),
        "trend": "stable",
        "years": Decimal("3.0"),
        "confidence": 79,
        "ai_note": (
            "Rental income from 123 Oak St verified via Schedule E and lease "
            "agreement. Net rental income of $650/mo after expenses per Fannie "
            "Mae guidelines. Note: confidence is 79% — recommend manual "
            "verification of lease terms."
        ),
        "mismo": (
            {
                "entity": "INCOME",
                "field": "RentalNetMonthly",
                "value": "$650.00",
                "confidence": 79,
            },
            {
                "entity": "PROPERTY",
                "field": "RentalAddress",
                "value": "123 Oak St, Unit B",
                "confidence": 92,
            },
            {
                "entity": "INCOME",
                "field": "RentalGrossMonthly",
                "value": "$1,200.00",
                "confidence": 91,
            },
        ),
        "docs": ("1040 Schedule E (2025)", "1040 Schedule E (2024)", "Lease agreement"),
        "borrower_id": PRIMARY_BORROWER_ID,
        "borrower_name": PRIMARY_BORROWER_NAME,
        "category": "non_employment",
        "employment_type": None,
        "start_date": "2023-01-01",
        "tenure_years": 3,
        "tenure_months": 0,
        "base_salary": None,
        "overtime": None,
        "bonus": None,
        "commission": None,
        "total_qualifying": Decimal("650.00"),
        "voe": None,
        "mismo_paths": {
            "employer_path": "",
            "income_path": ("Loan.Borrowers.Borrower[0].OtherIncomes.OtherIncome[0]"),
        },
        "stated_monthly": Decimal("800.00"),
        "verified_monthly": Decimal("650.00"),
    },
)


# 3 canned DTI obligations — PITIA first (housing), then recurring debts.
# Order preserved by `sort_order` so the DTI tab renders
# deterministically regardless of insert timing.
DTI_ITEMS: tuple[_DtiItem, ...] = (
    {"description": "Proposed PITIA (P&I + Tax + Insurance)", "monthly": Decimal("2984.71")},
    {"description": "Auto loan — Chase Bank", "monthly": Decimal("380.00")},
    {"description": "Student loan — Navient", "monthly": Decimal("250.00")},
)


# ---------------------------------------------------------------------------
# Packet-level metadata: applied rules, findings, evidence trace,
# optional VA residual income, and overall confidence.
# ---------------------------------------------------------------------------

APPLIED_RULES: _AppliedRules = {
    "program_id": "conventional",
    "dti_limit": 45.0,
    "guidelines": "Fannie Mae Selling Guide B3-3",
    "trending_method": "averaged",
    "residual_income_required": False,
}

# Conventional packet — no VA residual income. Populated as a canned
# example when a packet is declared VA, left None otherwise.
RESIDUAL_INCOME: _ResidualIncome | None = None


INCOME_FINDINGS: tuple[_IncomeFinding, ...] = (
    {
        "finding_id": "IF-01",
        "severity": "review",
        "category": "variance",
        "description": (
            "Rental income stated at $800/month on URLA exceeds net verified "
            "rental income of $650/month — a $150/month overstatement."
        ),
        "recommendation": (
            "Use verified net rental income ($650/mo) for qualification. "
            "Re-disclose if borrower contests."
        ),
        "affected_sources": ("I-04",),
        "mismo_refs": ("INCOME.RentalNetMonthly", "INCOME.RentalGrossMonthly"),
    },
    {
        "finding_id": "IF-02",
        "severity": "info",
        "category": "trending_concern",
        "description": (
            "Overtime income shows an increasing 3-year trend ($720 → $780). "
            "Averaging method used per Fannie B3-3.1-01."
        ),
        "recommendation": (
            "No action required. Flag for re-verification if overtime drops "
            "materially at next refresh."
        ),
        "affected_sources": ("I-02",),
        "mismo_refs": ("INCOME.OvertimeMonthly", "INCOME.OvertimeTrend"),
    },
    {
        "finding_id": "IF-03",
        "severity": "info",
        "category": "incomplete_verification",
        "description": (
            "Rental income confidence (79%) below auto-approve threshold. "
            "Lease agreement on file but end date not clearly OCR'd."
        ),
        "recommendation": (
            "Manually verify lease term and remaining months. If < 12 months "
            "remaining, reduce qualifying rental to 75% gross."
        ),
        "affected_sources": ("I-04",),
        "mismo_refs": ("INCOME.RentalNetMonthly",),
    },
)


INCOME_EVIDENCE: tuple[_EvidenceTrace, ...] = (
    {
        "document_id": "DOC-URLA",
        "page": 3,
        "mismo_path": ("Loan.Borrowers.Borrower[0].Employers.Employer[0].Employer.Name"),
        "snippet": "Employer: Midwest Engineering Corp",
    },
    {
        "document_id": "DOC-W2-2025",
        "page": 1,
        "mismo_path": (
            "Loan.Borrowers.Borrower[0].Employers.Employer[0]"
            ".CurrentIncomeItems.CurrentIncomeItem[0].Amount"
        ),
        "snippet": "Wages, tips, other compensation: $112,400.00",
    },
    {
        "document_id": "DOC-PAYSTUB",
        "page": 1,
        "mismo_path": (
            "Loan.Borrowers.Borrower[0].Employers.Employer[0]"
            ".CurrentIncomeItems.CurrentIncomeItem[1].Amount"
        ),
        "snippet": "YTD overtime: $1,950.00 (3 months)",
    },
    {
        "document_id": "DOC-1040-SCHE-2025",
        "page": 2,
        "mismo_path": ("Loan.Borrowers.Borrower[0].OtherIncomes.OtherIncome[0].Amount"),
        "snippet": "Line 3 (rents received): $14,400; expenses: $6,600",
    },
)


OVERALL_CONFIDENCE: int = 88
