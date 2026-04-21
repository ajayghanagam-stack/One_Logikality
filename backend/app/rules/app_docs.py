"""Per-micro-app required-document manifest (US-5.1).

Maps each downstream micro-app to the MISMO 3.6 document types it needs
to produce a complete result. Ported 1:1 from the demo's
`APP_REQUIRED_DOCS` in `lib/demo-data.ts`; the `mismo_type` values match
the types recorded on `ecv_documents.mismo_type` so the dashboard can
compute gating by set-subtracting found docs from this manifest.

ECV itself has no required-docs manifest — it processes whatever is
uploaded and is the source of every other app's document inventory, so
gating ECV on ECV output would be circular.
"""

from __future__ import annotations

from typing import TypedDict


class RequiredDoc(TypedDict):
    """One MISMO doc type an app needs + a human-readable reason.

    `reason` is surfaced verbatim on the blocked-app dialog so the
    underwriter understands why each missing doc matters, not just that
    something is missing.
    """

    mismo_type: str
    reason: str


# { micro_app_id: [ RequiredDoc, ... ] }
# Only downstream apps appear here. Absence of an entry means "no
# gating" (used for "ecv" — never blocked).
APP_REQUIRED_DOCS: dict[str, tuple[RequiredDoc, ...]] = {
    "title-search": (
        {
            "mismo_type": "TITLE_COMMITMENT",
            "reason": "Core document for chain-of-title analysis",
        },
        {
            "mismo_type": "WARRANTY_DEED",
            "reason": "Establishes current ownership and vesting",
        },
        {
            "mismo_type": "DEED_OF_TRUST",
            "reason": "Identifies existing mortgage liens",
        },
        {
            "mismo_type": "TAX_CERTIFICATE",
            "reason": "Confirms tax lien status on property",
        },
    ),
    "title-exam": (
        {
            "mismo_type": "TITLE_COMMITMENT",
            "reason": "Primary document for defect examination",
        },
        {
            "mismo_type": "WARRANTY_DEED",
            "reason": "Vesting and conveyance verification",
        },
        {
            "mismo_type": "DEED_OF_TRUST",
            "reason": "Lien and encumbrance analysis",
        },
    ),
    "compliance": (
        {
            "mismo_type": "LOAN_ESTIMATE",
            "reason": "Required for TRID fee tolerance comparison",
        },
        {
            "mismo_type": "CLOSING_DISCLOSURE",
            "reason": "Required for TRID fee tolerance comparison",
        },
        {
            "mismo_type": "LEAD_PAINT_DISCLOSURE",
            "reason": "Federal disclosure requirement (pre-1978 homes)",
        },
        {
            "mismo_type": "STATE_DISCLOSURE",
            "reason": "State-specific disclosure requirements (Radon for IL)",
        },
        {
            "mismo_type": "AFFILIATED_BUSINESS",
            "reason": "RESPA affiliated business arrangement disclosure",
        },
        {
            "mismo_type": "URLA_1003",
            "reason": "HMDA data accuracy verification",
        },
    ),
    "income-calc": (
        {
            "mismo_type": "W2_WAGE_STATEMENT",
            "reason": "Primary employment income verification",
        },
        {
            "mismo_type": "PAYSTUB",
            "reason": "Current income and YTD verification",
        },
        {
            "mismo_type": "TAX_RETURN_1040",
            "reason": "2-year income history requirement",
        },
        {
            "mismo_type": "TAX_SCHEDULE_E",
            "reason": "Rental income verification (if applicable)",
        },
        {
            "mismo_type": "VOE",
            "reason": "Employment and income confirmation",
        },
        {
            "mismo_type": "URLA_1003",
            "reason": "Stated income comparison against verified income",
        },
    ),
}
