"""Three-tier rule system primitives (US-4.1 / US-4.4).

The rule catalog (`catalog`) captures industry-standard loan-program
defaults and the editable-rule schemas consumed by the UI rule editor.
The resolver (`resolver`) layers program defaults → org-level overrides →
packet-level overrides to produce the value actually used by pipeline
code and surfaced by the `ConfigApplied` badge.

Key strings (`dtiLimit`, `chainDepth`, etc.) are intentionally camelCase
to stay in lockstep with the demo reference AND with the frontend's
`lib/rules.ts` catalog — they travel over the wire as-is, and matching
keys on both sides removes a translation layer between Python and
TypeScript.
"""

from app.rules.app_docs import APP_REQUIRED_DOCS, RequiredDoc
from app.rules.catalog import (
    LOAN_PROGRAM_IDS,
    LOAN_PROGRAMS,
    MICRO_APP_RULES,
    RULE_APP_IDS,
    EditableRuleSchema,
    LoanProgramRules,
    RuleValue,
)
from app.rules.resolver import (
    EffectiveRule,
    RuleOverride,
    format_rule_value,
    get_effective_rules,
    get_org_value,
    get_program_default,
)
from app.rules.validator import find_schema, validate_rule_value

__all__ = [
    "APP_REQUIRED_DOCS",
    "EditableRuleSchema",
    "EffectiveRule",
    "LOAN_PROGRAM_IDS",
    "LOAN_PROGRAMS",
    "LoanProgramRules",
    "MICRO_APP_RULES",
    "RULE_APP_IDS",
    "RequiredDoc",
    "RuleOverride",
    "RuleValue",
    "find_schema",
    "format_rule_value",
    "get_effective_rules",
    "get_org_value",
    "get_program_default",
    "validate_rule_value",
]
