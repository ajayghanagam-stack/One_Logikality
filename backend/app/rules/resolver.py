"""Three-tier rule resolver (US-4.4).

Given a micro-app + active loan program + the two override layers, returns
the effective rule values the pipeline should use and the provenance the
UI needs for the `ConfigApplied` badge (which value came from where).

Precedence (highest wins):
  1. Packet-level override — carries `reason`, `overridden_at`,
     `overridden_by`; set by underwriter/examiner/compliance officer for
     a specific loan.
  2. Organization-level override — flat value-only map keyed by program;
     set by the customer admin and applied to every packet.
  3. Industry default — `LOAN_PROGRAMS[program_id][rule_key]`.

The signature mirrors the TypeScript resolver in
`one-logikality-demo/lib/effective-rules.ts` so we can trust identical
inputs produce identical outputs across the stack — crucial for the
`ConfigApplied` badge to stay consistent between the server-side pipeline
that *applies* rules and the client-side UI that *displays* them.

Override shapes are passed as plain dicts (not Pydantic/ORM objects) so
this module has zero DB coupling. It's safe to call from anywhere —
handlers, pipeline activities, tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from app.rules.catalog import (
    LOAN_PROGRAMS,
    MICRO_APP_RULES,
    EditableRuleSchema,
    RuleValue,
)


class RuleOverride(TypedDict):
    """One packet-level override.

    Stored per (micro_app_id, rule_key). `reason` is mandatory — the
    product rule is "every packet-level override carries an audit trail"
    and the API layer rejects empty strings (US-4.3).
    """

    value: RuleValue
    reason: str
    overridden_at: datetime
    overridden_by: str


# Typed aliases for the two override layers. Names match the TS source so
# reviewers flipping between files don't have to retranslate.
PacketRuleOverrides = dict[str, dict[str, RuleOverride]]
# { micro_app_id: { rule_key: RuleOverride } }

OrgConfigOverrides = dict[str, dict[str, RuleValue]]
# { program_id: { rule_key: value } }


@dataclass(frozen=True)
class EffectiveRule:
    """One rule, resolved. Carries full provenance so the UI can render
    "3 rules edited" + per-rule badges ("Org default: 45", "Overridden")
    without another round of lookups."""

    schema: EditableRuleSchema
    # Final value the pipeline should use. `None` means the program has
    # no default for this key AND neither override layer set it — the
    # title-exam schemas (exceptionClassification, vestingSensitivity)
    # are the only current case; the UI treats absence as "choose one".
    value: RuleValue | None
    overridden: bool
    override: RuleOverride | None
    org_overridden: bool
    org_value: RuleValue | None
    program_default: RuleValue | None


def get_effective_rules(
    micro_app_id: str,
    active_program_id: str,
    packet_overrides: PacketRuleOverrides,
    org_overrides: OrgConfigOverrides,
) -> list[EffectiveRule]:
    """Resolve the three layers for every rule on `micro_app_id`.

    Returns `[]` for unknown app ids. An unknown program id is handled
    the same way the TS resolver handles it: `program_default` stays
    `None` for every rule, and override layers still take precedence
    if present. Callers that need a hard error on unknown programs
    should validate upstream.
    """
    schemas = MICRO_APP_RULES.get(micro_app_id, [])
    program = LOAN_PROGRAMS.get(active_program_id)
    app_packet_overrides = packet_overrides.get(micro_app_id, {})
    program_org_overrides = org_overrides.get(active_program_id, {})

    results: list[EffectiveRule] = []
    for schema in schemas:
        key = schema["key"]
        program_default: RuleValue | None = (
            program.get(key) if program is not None else None  # type: ignore[arg-type]
        )

        has_org_override = key in program_org_overrides
        org_value: RuleValue | None = (
            program_org_overrides[key] if has_org_override else program_default
        )

        packet_override = app_packet_overrides.get(key)
        final_value: RuleValue | None = (
            packet_override["value"] if packet_override is not None else org_value
        )

        results.append(
            EffectiveRule(
                schema=schema,
                value=final_value,
                overridden=packet_override is not None,
                override=packet_override,
                org_overridden=has_org_override,
                org_value=org_value,
                program_default=program_default,
            )
        )
    return results


def get_program_default(program_id: str, rule_key: str) -> RuleValue | None:
    """Industry default for one rule, ignoring all overrides.

    Returns `None` if the program is unknown or the key isn't defined on
    the program (e.g., title-exam's `vestingSensitivity`, which has no
    program-level default).
    """
    program = LOAN_PROGRAMS.get(program_id)
    if program is None:
        return None
    return program.get(rule_key)  # type: ignore[arg-type]


def get_org_value(
    program_id: str,
    rule_key: str,
    org_overrides: OrgConfigOverrides,
) -> RuleValue | None:
    """Org-level effective value, ignoring packet overrides.

    Used by the org configuration page to show what "the org has set"
    without the per-packet noise.
    """
    override = org_overrides.get(program_id, {}).get(rule_key)
    if override is not None:
        return override
    return get_program_default(program_id, rule_key)


def format_rule_value(value: RuleValue | None, schema: EditableRuleSchema) -> str:
    """Render a rule value for display using its schema.

    Mirrors the TS `formatRuleValue` so the server-side PDF report and
    the client-side rule panel produce identical strings.
    """
    if value is None:
        return "—"
    rule_type = schema["type"]
    if rule_type == "toggle":
        return "Yes" if value else "No"
    if rule_type == "select":
        options = schema.get("options") or []
        for opt in options:
            if opt["value"] == value:
                return opt["label"]
        return str(value)
    if rule_type == "number":
        unit = schema.get("unit")
        return f"{value} {unit}" if unit else str(value)
    return str(value)
