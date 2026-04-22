"""Deterministic canned Title Examination findings (US-6.2).

Ported 1:1 from the `one-logikality-demo` reference
(`lib/demo-data.ts` → STANDARD_EXCEPTIONS, SPECIFIC_EXCEPTIONS,
REQUIREMENTS, WARNINGS, CHECKLIST_ITEMS) so the Title Exam page renders
the same ALTA schedule ordering and curative workflow. The ECV stub
writes these rows during the `score` stage alongside the other
micro-app findings.

The checklist items carry a `checked` boolean; items that the demo
pre-seeds as complete (delinquent taxes collected, HOA estoppel
requested, hazard insurance binder received) ship pre-checked so the
UI shows progress on first hydrate.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# TI Hub superset taxonomy — one of the values in
# `TITLE_EXAM_FLAG_TYPES` (models.py). Left as str for flexibility in the
# seed data; the DB CHECK constraint enforces the enum.
_FlagType = str

# Structured evidence — shape matches TI Hub's ExaminerFlag.evidence_refs.
_EvidenceRef = dict[str, Any]


class _StandardException(TypedDict):
    number: int
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    page_ref: str
    description: str
    note: str | None
    # TI Hub superset — standard ALTA exceptions are boilerplate, so
    # flag_type/ai_explanation/evidence_refs are typically None.
    flag_type: _FlagType | None
    ai_explanation: str | None
    evidence_refs: list[_EvidenceRef]


class _SpecificException(TypedDict):
    number: int
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    page_ref: str
    description: str
    note: str | None
    flag_type: _FlagType | None
    ai_explanation: str | None
    evidence_refs: list[_EvidenceRef]


class _Requirement(TypedDict):
    number: int
    title: str
    priority: Literal["must_close", "should_close", "recommended"]
    status: Literal["open", "requested", "provided", "not_ordered"]
    page_ref: str | None
    description: str
    note: str | None
    ai_explanation: str | None
    evidence_refs: list[_EvidenceRef]


class _Warning(TypedDict):
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    description: str
    note: str | None
    flag_type: _FlagType | None
    ai_explanation: str | None
    evidence_refs: list[_EvidenceRef]


class _ChecklistItem(TypedDict):
    number: int
    action: str
    priority: str  # "Critical" / "High" / "Medium" / "Recommended" (display-cased)
    checked: bool
    note: str | None


STANDARD_EXCEPTIONS: tuple[_StandardException, ...] = (
    {
        "number": 1,
        "title": "Taxes not yet due and payable",
        "severity": "low",
        "page_ref": "Sch. B-1",
        "description": (
            "Real estate taxes and assessments not yet due and payable as of the "
            "effective date of the policy."
        ),
        "note": None,
        # Standard ALTA exceptions are boilerplate — no risk flag attached.
        "flag_type": None,
        "ai_explanation": None,
        "evidence_refs": [],
    },
    {
        "number": 2,
        "title": "Rights of parties in possession",
        "severity": "medium",
        "page_ref": "Sch. B-2",
        "description": (
            "Rights and claims of parties in possession not shown by the public records."
        ),
        "note": None,
        "flag_type": None,
        "ai_explanation": None,
        "evidence_refs": [],
    },
    {
        "number": 3,
        "title": "Survey matters",
        "severity": "medium",
        "page_ref": "Sch. B-3",
        "description": (
            "Encroachments, overlaps, boundary line disputes, and other matters "
            "disclosed by an accurate and complete survey."
        ),
        "note": (
            "No survey was provided with this title commitment. Recommend obtaining "
            "an ALTA/NSPS survey prior to closing."
        ),
        "flag_type": None,
        "ai_explanation": None,
        "evidence_refs": [],
    },
    {
        "number": 4,
        "title": "Easements and servitudes not of record",
        "severity": "low",
        "page_ref": "Sch. B-4",
        "description": "Easements or claims of easements not shown by the public records.",
        "note": None,
        "flag_type": None,
        "ai_explanation": None,
        "evidence_refs": [],
    },
    {
        "number": 5,
        "title": "Mechanics' and materialmen's liens",
        "severity": "medium",
        "page_ref": "Sch. B-5",
        "description": (
            "Any lien or right to a lien for services, labor, or material heretofore "
            "or hereafter furnished, imposed by law and not shown by the public records."
        ),
        "note": None,
        "flag_type": None,
        "ai_explanation": None,
        "evidence_refs": [],
    },
)


SPECIFIC_EXCEPTIONS: tuple[_SpecificException, ...] = (
    {
        "number": 6,
        "title": "Unreleased mortgage — First National Bank",
        "severity": "critical",
        "page_ref": "p. 42, 78",
        "description": (
            "Open mortgage recorded 2019-03-15 as Instrument No. 2019-042871, in "
            "the original principal amount of $312,000, from Jane A. Smith to First "
            "National Bank. No satisfaction or release of record."
        ),
        "note": (
            "Must be released or paid off at closing. Obtain payoff statement from "
            "First National Bank."
        ),
        "flag_type": "unreleased_mortgage",
        "ai_explanation": (
            "Recording index shows the 2019 mortgage instrument but no "
            "corresponding satisfaction, discharge, or release has been "
            "recorded. The lien remains open and would survive closing absent "
            "a payoff-and-release coordinated with the lender."
        ),
        "evidence_refs": [
            {
                "page_number": 42,
                "text_snippet": (
                    "Mortgage recorded 2019-03-15, Inst. 2019-042871, "
                    "principal $312,000, mortgagor Jane A. Smith, mortgagee "
                    "First National Bank."
                ),
            },
            {
                "page_number": 78,
                "text_snippet": (
                    "No satisfaction of mortgage Inst. 2019-042871 found "
                    "in the recorder's index as of the effective date."
                ),
            },
        ],
    },
    {
        "number": 7,
        "title": "Chain of title gap — 2008 to 2012",
        "severity": "critical",
        "page_ref": "p. 14, 22",
        "description": (
            "Four-year gap between Johnson Family Trust's acquisition (Grant Deed, "
            "Inst #2008-031244) and the subsequent Warranty Deed to Jane A. Smith "
            "(Inst #2012-048721). No intermediate conveyance of record."
        ),
        "note": (
            "Requires quiet title action or affidavit from trustee confirming no "
            "intermediate transfers."
        ),
        "flag_type": "chain_of_title_gap",
        "ai_explanation": (
            "The recorded conveyances jump directly from the 2008 Grant "
            "Deed into the Johnson Family Trust to a 2012 Warranty Deed "
            "out to a new grantee. No intermediate transfer appears in the "
            "index, so the trust's authority to convey in 2012 cannot be "
            "confirmed from the record alone."
        ),
        "evidence_refs": [
            {
                "page_number": 14,
                "text_snippet": (
                    "Grant Deed, Inst. 2008-031244, Johnson Family Trust "
                    "grantee; recorded 2008-11-03."
                ),
            },
            {
                "page_number": 22,
                "text_snippet": (
                    "Warranty Deed, Inst. 2012-048721, Jane A. Smith "
                    "grantee; recorded 2012-06-15. No intermediate "
                    "conveyance of record."
                ),
            },
        ],
    },
    {
        "number": 8,
        "title": "Utility easement — non-standard terms",
        "severity": "high",
        "page_ref": "Book 1847, Pg 233",
        "description": (
            "Utility easement recorded 2001-04-10 in favor of Springfield Power "
            "Company containing non-standard provision requiring property owner to "
            "bear 50% of maintenance and repair costs."
        ),
        "note": "Unusual cost-sharing provision. Disclose to buyer in writing.",
        "flag_type": "unacceptable_exception",
        "ai_explanation": (
            "Residential utility easements rarely shift maintenance cost "
            "to the landowner. The 50% cost-sharing clause departs from "
            "standard ALTA utility-easement language and would usually "
            "require affirmative disclosure to the purchaser before it is "
            "accepted as a Schedule B exception."
        ),
        "evidence_refs": [
            {
                "page_number": 61,
                "text_snippet": (
                    "Easement to Springfield Power Co., Book 1847 Pg 233, "
                    "§3: 'Grantor shall bear fifty percent (50%) of all "
                    "maintenance and repair costs of the easement area.'"
                ),
            }
        ],
    },
    {
        "number": 9,
        "title": "Restrictive covenants — HOA",
        "severity": "low",
        "page_ref": "Book 920, Pg 114",
        "description": (
            "Declaration of restrictive covenants for Evergreen Terrace Homeowners "
            "Association recorded 1996-01-15, including residential-only use and "
            "architectural approval requirements."
        ),
        "note": None,
        "flag_type": "unacceptable_exception",
        "ai_explanation": (
            "Standard subdivision CC&Rs running with the land. Not a risk "
            "flag on its own — surfaced as an exception so downstream "
            "closing systems can confirm HOA estoppel before policy issues."
        ),
        "evidence_refs": [
            {
                "page_number": 34,
                "text_snippet": (
                    "Declaration of CC&Rs for Evergreen Terrace HOA, "
                    "Book 920 Pg 114, recorded 1996-01-15."
                ),
            }
        ],
    },
    {
        "number": 10,
        "title": "Delinquent property taxes",
        "severity": "high",
        "page_ref": "TL-2024-4421",
        "description": (
            "Property tax lien recorded 2024-09-01 for delinquent 2023 second-"
            "installment property taxes in the amount of $2,847.22."
        ),
        "note": "Must be paid at or before closing from seller's proceeds.",
        "flag_type": "tax_issue",
        "ai_explanation": (
            "An unpaid property tax lien is a statutory first lien ahead "
            "of the insured mortgage and would render the policy defective "
            "if left unresolved. The amount and recording instrument "
            "match the county treasurer's delinquency roll."
        ),
        "evidence_refs": [
            {
                "page_number": 55,
                "text_snippet": (
                    "Tax Lien TL-2024-4421, recorded 2024-09-01, amount "
                    "$2,847.22, tax year 2023 second installment."
                ),
            }
        ],
    },
    {
        "number": 11,
        "title": "Vesting name variance",
        "severity": "medium",
        "page_ref": "p. 3, 67",
        "description": (
            "Warranty Deed recorded 2012-06-15 shows grantee as 'Jane Smyth'. Title "
            "Commitment reflects insured as 'Jane Smith'."
        ),
        "note": (
            "Likely clerical error. Request corrective deed or scrivener's affidavit "
            "prior to closing."
        ),
        "flag_type": "name_discrepancy",
        "ai_explanation": (
            "The vesting deed spells the grantee 'Smyth' while every "
            "subsequent instrument and the commitment use 'Smith'. The "
            "surrounding identifiers (address, SSN-4, execution date) "
            "match, so this reads as a scrivener's error rather than a "
            "stranger to title — but needs a corrective instrument before "
            "policy issues."
        ),
        "evidence_refs": [
            {
                "page_number": 3,
                "text_snippet": ("Commitment Schedule A vesting: 'Jane Smith, a single woman'."),
            },
            {
                "page_number": 67,
                "text_snippet": (
                    "Warranty Deed, Inst. 2012-048721: '… to Jane Smyth, a single woman, …'"
                ),
            },
        ],
    },
    {
        "number": 12,
        "title": "Judgment search — none found",
        "severity": "low",
        "page_ref": "Dockets searched",
        "description": (
            "Search of state and federal judgment dockets for Jane A. Smith returned "
            "no liens, judgments, or pending litigation as of the effective date."
        ),
        "note": None,
        # Clean judgment search is informational, not a risk — no flag_type.
        "flag_type": None,
        "ai_explanation": None,
        "evidence_refs": [],
    },
)


REQUIREMENTS: tuple[_Requirement, ...] = (
    {
        "number": 1,
        "title": "Satisfaction of First National Bank mortgage",
        "priority": "must_close",
        "status": "open",
        "page_ref": "p. 42",
        "description": (
            "Obtain and record full satisfaction of the mortgage held by First "
            "National Bank, Inst #2019-042871, at or before closing."
        ),
        "note": "Payoff statement requested — awaiting lender response.",
        "ai_explanation": (
            "Tied to the unreleased-mortgage exception. Without a recorded "
            "release, the policy cannot be issued free and clear of the 2019 "
            "lien."
        ),
        "evidence_refs": [
            {
                "page_number": 42,
                "text_snippet": (
                    "Mortgage Inst. 2019-042871 in favor of First National "
                    "Bank — no release of record."
                ),
            }
        ],
    },
    {
        "number": 2,
        "title": "Resolve chain of title gap (2008–2012)",
        "priority": "must_close",
        "status": "open",
        "page_ref": "p. 14",
        "description": (
            "Obtain recorded instrument, affidavit, or quiet title judgment resolving "
            "the four-year gap in the chain of title."
        ),
        "note": None,
        "ai_explanation": (
            "Required to close the chain-of-title gap exception. A trustee "
            "affidavit is usually sufficient if the trust's original "
            "acquisition deed and the 2012 conveyance share the same legal "
            "description."
        ),
        "evidence_refs": [
            {
                "page_number": 14,
                "text_snippet": (
                    "Gap between Inst. 2008-031244 and Inst. 2012-048721 "
                    "in the grantor/grantee index."
                ),
            }
        ],
    },
    {
        "number": 3,
        "title": "Payment of delinquent property taxes",
        "priority": "must_close",
        "status": "open",
        "page_ref": "TL-2024-4421",
        "description": (
            "Pay outstanding 2023 property tax balance of $2,847.22 and record "
            "satisfaction of tax lien TL-2024-4421."
        ),
        "note": "Will be paid from seller proceeds at closing.",
        "ai_explanation": (
            "Property tax liens are statutory first liens and must be "
            "satisfied before issuing a lender's policy."
        ),
        "evidence_refs": [
            {
                "page_number": 55,
                "text_snippet": "Tax Lien TL-2024-4421, balance $2,847.22.",
            }
        ],
    },
    {
        "number": 4,
        "title": "Corrective deed for vesting name variance",
        "priority": "should_close",
        "status": "open",
        "page_ref": "p. 67",
        "description": (
            "Record corrective warranty deed or scrivener's affidavit correcting "
            "grantee name from 'Jane Smyth' to 'Jane Smith'."
        ),
        "note": None,
        "ai_explanation": (
            "Paired with the vesting-name-variance exception. Corrective "
            "instrument preferred; scrivener's affidavit acceptable if the "
            "seller cannot locate the original grantor."
        ),
        "evidence_refs": [
            {
                "page_number": 67,
                "text_snippet": "Grantee shown as 'Jane Smyth' on Inst. 2012-048721.",
            }
        ],
    },
    {
        "number": 5,
        "title": "ALTA/NSPS boundary survey",
        "priority": "recommended",
        "status": "not_ordered",
        "page_ref": None,
        "description": (
            "Obtain current ALTA/NSPS Land Title Survey to identify any "
            "encroachments, overlaps, or boundary disputes."
        ),
        "note": "Optional — buyer may request survey exception removal.",
        "ai_explanation": (
            "Optional for the lender's policy but commonly required by "
            "purchasers to remove the standard survey exception from the "
            "owner's policy."
        ),
        "evidence_refs": [],
    },
    {
        "number": 6,
        "title": "HOA estoppel certificate",
        "priority": "should_close",
        "status": "requested",
        "page_ref": "Book 920, Pg 114",
        "description": (
            "Obtain estoppel certificate from Evergreen Terrace HOA confirming no "
            "outstanding assessments or violations."
        ),
        "note": None,
        "ai_explanation": (
            "Required to confirm no unpaid assessments or architectural "
            "violations exist against the parcel under the recorded CC&Rs."
        ),
        "evidence_refs": [
            {
                "page_number": 34,
                "text_snippet": ("Declaration of CC&Rs, Evergreen Terrace HOA, Book 920 Pg 114."),
            }
        ],
    },
    {
        "number": 7,
        "title": "Hazard insurance binder",
        "priority": "must_close",
        "status": "provided",
        "page_ref": None,
        "description": (
            "Lender requires hazard insurance binder naming First National Bank as "
            "mortgagee with minimum coverage of $385,000."
        ),
        "note": "Binder received from Acme Insurance on Mar 27, 2026.",
        "ai_explanation": (
            "Already provided — marked as satisfied because Acme "
            "Insurance binder was received and matches the lender's "
            "coverage and loss-payee requirements."
        ),
        "evidence_refs": [],
    },
)


WARNINGS: tuple[_Warning, ...] = (
    {
        "severity": "critical",
        "title": "Active mortgage must be paid",
        "description": (
            "The First National Bank mortgage of $312,000 is actively encumbering "
            "the property. Title cannot convey free and clear without satisfaction "
            "of this lien."
        ),
        "note": (
            "Coordinate payoff with seller's lender. Obtain payoff statement and "
            "wire instructions at least 48 hours before closing."
        ),
        "flag_type": "unreleased_mortgage",
        "ai_explanation": (
            "Same underlying defect as the unreleased-mortgage Schedule B "
            "exception, restated as an actionable warning so the curative "
            "team coordinates the lender payoff timeline directly."
        ),
        "evidence_refs": [
            {
                "page_number": 42,
                "text_snippet": "Mortgage Inst. 2019-042871 — no satisfaction of record.",
            }
        ],
    },
    {
        "severity": "critical",
        "title": "Chain of title defect",
        "description": (
            "Four-year gap in ownership records between 2008 and 2012 creates a "
            "cloud on title that must be resolved by corrective instrument or quiet "
            "title action."
        ),
        "note": (
            "Consider requiring seller to obtain trustee affidavit at their expense. "
            "Alternatively, title insurance may provide affirmative coverage pending "
            "curative."
        ),
        "flag_type": "chain_of_title_gap",
        "ai_explanation": (
            "Gap in the grantor index leaves the 2012 grantor's authority "
            "to convey unproved on the face of the record. Affirmative "
            "coverage is only a defensible substitute if the underwriter "
            "accepts the associated risk."
        ),
        "evidence_refs": [
            {
                "page_number": 14,
                "text_snippet": "2008 Grant Deed, Inst. 2008-031244.",
            },
            {
                "page_number": 22,
                "text_snippet": "2012 Warranty Deed, Inst. 2012-048721.",
            },
        ],
    },
    {
        "severity": "high",
        "title": "Non-standard easement provision",
        "description": (
            "The Springfield Power utility easement contains unusual 50% maintenance "
            "cost-sharing clause not typically found in residential utility easements."
        ),
        "note": (
            "Disclose this provision in writing to buyer at least 10 days before closing per RESPA."
        ),
        "flag_type": "unacceptable_exception",
        "ai_explanation": (
            "The cost-sharing clause is atypical for residential utility "
            "easements and may be a material disclosure under RESPA's "
            "pre-closing disclosure window."
        ),
        "evidence_refs": [
            {
                "page_number": 61,
                "text_snippet": (
                    "Easement to Springfield Power Co., §3, 50% maintenance cost-sharing clause."
                ),
            }
        ],
    },
    {
        "severity": "medium",
        "title": "Survey exception not cleared",
        "description": (
            "No current survey on file. Schedule B contains standard survey "
            "exceptions that could be removed with ALTA/NSPS survey."
        ),
        "note": None,
        "flag_type": "document_defect",
        "ai_explanation": (
            "Absent an up-to-date ALTA/NSPS survey, the standard survey "
            "exceptions remain in place — acceptable for the lender's "
            "policy, material for an owner's policy."
        ),
        "evidence_refs": [],
    },
)


CHECKLIST_ITEMS: tuple[_ChecklistItem, ...] = (
    {
        "number": 1,
        "action": "Request mortgage payoff from First National Bank",
        "priority": "Critical",
        "checked": False,
        "note": "Payoff required 48 hours before closing",
    },
    {
        "number": 2,
        "action": "Obtain trustee affidavit for 2008–2012 chain gap",
        "priority": "Critical",
        "checked": False,
        "note": "Or quiet title action",
    },
    {
        "number": 3,
        "action": "Collect delinquent tax balance at closing",
        "priority": "Critical",
        "checked": True,
        "note": "Included in HUD-1 line 213",
    },
    {
        "number": 4,
        "action": "Record corrective deed for name variance",
        "priority": "High",
        "checked": False,
        "note": None,
    },
    {
        "number": 5,
        "action": "Disclose utility easement cost-sharing in writing",
        "priority": "High",
        "checked": False,
        "note": "RESPA 10-day disclosure",
    },
    {
        "number": 6,
        "action": "Request HOA estoppel certificate",
        "priority": "Medium",
        "checked": True,
        "note": "Requested Mar 20, awaiting response",
    },
    {
        "number": 7,
        "action": "Order ALTA/NSPS survey",
        "priority": "Recommended",
        "checked": False,
        "note": "Optional — buyer discretion",
    },
    {
        "number": 8,
        "action": "Verify hazard insurance binder received",
        "priority": "High",
        "checked": True,
        "note": "Received from Acme Insurance Mar 27",
    },
)
