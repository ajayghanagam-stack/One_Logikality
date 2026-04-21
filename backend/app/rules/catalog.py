"""Industry-default rule catalog (US-4.1).

Two constants, both ported directly from the demo's `lib/demo-data.ts`:

- `LOAN_PROGRAMS` — the six supported loan programs with the
  industry-default rule values per GSE / HUD / VA / USDA / ALTA / investor
  guidance. Customer admins can override specific fields per program;
  the program catalog itself is not customer-editable.
- `MICRO_APP_RULES` — per-micro-app schemas describing which program
  fields are exposed to the rule editor, their input types, units, and
  option lists. A rule's `key` is the field name it overrides on
  `LoanProgramRules`.

Key strings are intentionally camelCase (not Python snake_case) so they
match the frontend catalog 1:1 and travel over the wire unchanged. The
N815 warning is suppressed module-wide via noqa on the TypedDict because
every field is camelCase by design.
"""

from __future__ import annotations

from typing import Literal, TypedDict

# Primitive value types a rule can hold. Mirrors the TS union.
RuleValue = str | int | float | bool


class LoanProgramRules(TypedDict):
    """Industry-default values for one loan program.

    The key strings live in camelCase on purpose — they're the wire
    contract with the frontend, and the `schema.key` pointers in
    `MICRO_APP_RULES` reference these names directly.
    """

    id: str
    label: str
    description: str
    # ECV confidence floor below which the overall packet is rejected.
    confidenceThreshold: int  # noqa: N815
    # Title chain-of-title depth in years.
    chainDepth: int  # noqa: N815
    judgmentScope: Literal["state", "both"]  # noqa: N815
    regulatoryFramework: str  # noqa: N815
    disclosureSet: str  # noqa: N815
    guidelines: str
    dtiLimit: int  # noqa: N815
    trendingMethod: Literal["averaged", "declining"]  # noqa: N815
    residualIncome: bool  # noqa: N815


class EditableRuleSchemaOption(TypedDict):
    value: str
    label: str


class EditableRuleSchema(TypedDict, total=False):
    """How the rule editor renders (and constrains) one rule.

    `total=False` because only number rules carry `min`/`max`/`unit` and
    only selects carry `options`. `key`, `label`, `type` are always
    present — the runtime checks in the resolver rely on that.
    """

    key: str
    label: str
    type: Literal["number", "select", "toggle"]
    unit: str
    min: int
    max: int
    options: list[EditableRuleSchemaOption]
    helpText: str  # noqa: N815


LOAN_PROGRAMS: dict[str, LoanProgramRules] = {
    "conventional": {
        "id": "conventional",
        "label": "Conventional Conforming",
        "description": "Fannie Mae / Freddie Mac conforming loans within loan limits",
        "confidenceThreshold": 85,
        "chainDepth": 30,
        "judgmentScope": "both",
        "regulatoryFramework": "CFPB 2026",
        "disclosureSet": "TRID + Federal + State",
        "guidelines": "Fannie Mae Selling Guide",
        "dtiLimit": 45,
        "trendingMethod": "averaged",
        "residualIncome": False,
    },
    "jumbo": {
        "id": "jumbo",
        "label": "Jumbo / Non-Conforming",
        "description": (
            "Loan amounts above conforming limits, typically portfolio or private investor"
        ),
        "confidenceThreshold": 95,
        "chainDepth": 40,
        "judgmentScope": "both",
        "regulatoryFramework": "CFPB 2026 + Investor overlays",
        "disclosureSet": "TRID + Federal + State + Portfolio",
        "guidelines": "Investor-specific (varies)",
        "dtiLimit": 43,
        "trendingMethod": "averaged",
        "residualIncome": False,
    },
    "fha": {
        "id": "fha",
        "label": "FHA",
        "description": "Federal Housing Administration insured loans",
        "confidenceThreshold": 80,
        "chainDepth": 30,
        "judgmentScope": "both",
        "regulatoryFramework": "CFPB 2026 + HUD",
        "disclosureSet": "TRID + Federal + State + FHA specific",
        "guidelines": "HUD Handbook 4000.1",
        "dtiLimit": 50,
        "trendingMethod": "averaged",
        "residualIncome": False,
    },
    "va": {
        "id": "va",
        "label": "VA",
        "description": "Veterans Affairs guaranteed loans",
        "confidenceThreshold": 82,
        "chainDepth": 30,
        "judgmentScope": "both",
        "regulatoryFramework": "CFPB 2026 + VA",
        "disclosureSet": "TRID + Federal + State + VA specific",
        "guidelines": "VA Lenders Handbook 26-7",
        "dtiLimit": 41,
        "trendingMethod": "averaged",
        "residualIncome": True,
    },
    "usda": {
        "id": "usda",
        "label": "USDA Rural Development",
        "description": "USDA Single Family Housing Guaranteed Loan Program",
        "confidenceThreshold": 82,
        "chainDepth": 30,
        "judgmentScope": "both",
        "regulatoryFramework": "CFPB 2026 + USDA",
        "disclosureSet": "TRID + Federal + State + USDA specific",
        "guidelines": "USDA HB-1-3555",
        "dtiLimit": 41,
        "trendingMethod": "averaged",
        "residualIncome": False,
    },
    "nonqm": {
        "id": "nonqm",
        "label": "Non-QM / Alternative Doc",
        "description": "Bank statement, DSCR, asset depletion, and other non-QM programs",
        "confidenceThreshold": 95,
        "chainDepth": 40,
        "judgmentScope": "both",
        "regulatoryFramework": "CFPB 2026 + Investor overlays",
        "disclosureSet": "TRID + Federal + State + Non-QM specific",
        "guidelines": "Investor-specific (Bank statement, DSCR, Asset depletion)",
        "dtiLimit": 50,
        "trendingMethod": "averaged",
        "residualIncome": False,
    },
}


# Tuple of program ids for validation (check-constraints, Pydantic Literal
# narrowing at API boundaries). Kept in declaration order so UIs that
# iterate this constant render the same program order as the demo.
LOAN_PROGRAM_IDS: tuple[str, ...] = tuple(LOAN_PROGRAMS.keys())


MICRO_APP_RULES: dict[str, list[EditableRuleSchema]] = {
    "compliance": [
        {
            "key": "regulatoryFramework",
            "label": "Regulatory framework",
            "type": "select",
            "options": [
                {"value": "CFPB 2026", "label": "CFPB 2026"},
                {"value": "CFPB 2026 + HUD", "label": "CFPB 2026 + HUD"},
                {"value": "CFPB 2026 + VA", "label": "CFPB 2026 + VA"},
                {"value": "CFPB 2026 + USDA", "label": "CFPB 2026 + USDA"},
                {
                    "value": "CFPB 2026 + Investor overlays",
                    "label": "CFPB 2026 + Investor overlays",
                },
            ],
            "helpText": (
                "Base regulatory framework applied to disclosure timing, "
                "fee tolerances, and truth-in-lending checks."
            ),
        },
        {
            "key": "disclosureSet",
            "label": "Disclosure set",
            "type": "select",
            "options": [
                {"value": "TRID + Federal + State", "label": "TRID + Federal + State"},
                {
                    "value": "TRID + Federal + State + FHA specific",
                    "label": "TRID + Federal + State + FHA specific",
                },
                {
                    "value": "TRID + Federal + State + VA specific",
                    "label": "TRID + Federal + State + VA specific",
                },
                {
                    "value": "TRID + Federal + State + USDA specific",
                    "label": "TRID + Federal + State + USDA specific",
                },
                {
                    "value": "TRID + Federal + State + Portfolio",
                    "label": "TRID + Federal + State + Portfolio",
                },
                {
                    "value": "TRID + Federal + State + Non-QM specific",
                    "label": "TRID + Federal + State + Non-QM specific",
                },
            ],
            "helpText": (
                "Which disclosure requirements to verify. Program-specific "
                "disclosures (e.g., FHA Amendatory Clause) are added based "
                "on program type."
            ),
        },
    ],
    "income-calc": [
        {
            "key": "dtiLimit",
            "label": "DTI limit",
            "type": "number",
            "unit": "%",
            "min": 30,
            "max": 60,
            "helpText": (
                "Maximum debt-to-income ratio for qualification. May be "
                "loosened for strong compensating factors (reserves, LTV, "
                "credit score)."
            ),
        },
        {
            "key": "guidelines",
            "label": "Underwriting guidelines",
            "type": "select",
            "options": [
                {
                    "value": "Fannie Mae Selling Guide",
                    "label": "Fannie Mae Selling Guide",
                },
                {
                    "value": "Freddie Mac Single-Family Seller/Servicer Guide",
                    "label": "Freddie Mac Seller/Servicer Guide",
                },
                {
                    "value": "HUD Handbook 4000.1",
                    "label": "HUD Handbook 4000.1 (FHA)",
                },
                {
                    "value": "VA Lenders Handbook 26-7",
                    "label": "VA Lenders Handbook 26-7",
                },
                {"value": "USDA HB-1-3555", "label": "USDA HB-1-3555"},
                {
                    "value": "Investor-specific (varies)",
                    "label": "Investor-specific (varies)",
                },
            ],
            "helpText": (
                "Which underwriting guideline authority is used for income calculation rules."
            ),
        },
        {
            "key": "trendingMethod",
            "label": "Income trending method",
            "type": "select",
            "options": [
                {"value": "averaged", "label": "Averaged (2-year average)"},
                {
                    "value": "declining",
                    "label": "Declining (conservative — use lowest year)",
                },
            ],
            "helpText": (
                "Averaged is standard; Declining uses the lowest annual "
                "amount from the 2-year history (conservative)."
            ),
        },
        {
            "key": "residualIncome",
            "label": "Residual income required",
            "type": "toggle",
            "helpText": (
                "Required for VA loans. Calculates net income after all "
                "obligations against VA regional tables."
            ),
        },
    ],
    "title-search": [
        {
            "key": "chainDepth",
            "label": "Chain-of-title depth",
            "type": "number",
            "unit": "years",
            "min": 20,
            "max": 60,
            "helpText": (
                "How many years back to trace chain of title. 30 years is "
                "standard; jumbo/non-QM typically 40."
            ),
        },
        {
            "key": "judgmentScope",
            "label": "Judgment search scope",
            "type": "select",
            "options": [
                {"value": "state", "label": "State courts only"},
                {"value": "both", "label": "State + Federal (PACER)"},
            ],
            "helpText": "Which court systems to search for judgments and liens.",
        },
    ],
    "title-exam": [
        {
            "key": "exceptionClassification",
            "label": "Exception classification standard",
            "type": "select",
            "options": [
                {"value": "ALTA", "label": "ALTA standard"},
                {"value": "State-specific", "label": "State-specific overlay"},
            ],
            "helpText": (
                "Which ALTA standards apply. Some states (CA, NY, TX) have specific overlays."
            ),
        },
        {
            "key": "vestingSensitivity",
            "label": "Vesting mismatch sensitivity",
            "type": "select",
            "options": [
                {"value": "Strict", "label": "Strict (flag any mismatch)"},
                {
                    "value": "Moderate",
                    "label": "Moderate (flag material mismatches)",
                },
                {
                    "value": "Lenient",
                    "label": "Lenient (only flag substantive defects)",
                },
            ],
            "helpText": ("How aggressively to flag name/identity variances between documents."),
        },
    ],
}


# Micro-apps that have editable rules. `ecv` is notably absent — ECV is the
# foundation layer; its thresholds come from the program defaults
# directly, not a customer-editable schema. Keeping this tuple separate
# from `models.APP_IDS` documents that distinction.
RULE_APP_IDS: tuple[str, ...] = tuple(MICRO_APP_RULES.keys())
