"""Three-tier rule resolver unit tests (US-4.4).

These tests are pure-Python — no DB, no HTTP client — because the
resolver is intentionally side-effect-free. They cover:

  * precedence (program default → org override → packet override)
  * unknown app / unknown program fallthrough
  * provenance flags on `EffectiveRule` (overridden / org_overridden)
  * `format_rule_value` across all three schema types
  * helpers `get_program_default` / `get_org_value`

If the TypeScript resolver and this one diverge, mortgage decisions the
pipeline makes won't match what the UI tells the user it applied. So the
contract here is "bit-for-bit identical outputs for identical inputs" —
worth the test surface.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.rules import (
    LOAN_PROGRAMS,
    MICRO_APP_RULES,
    EffectiveRule,
    RuleOverride,
    format_rule_value,
    get_effective_rules,
    get_org_value,
    get_program_default,
)


def _by_key(rules: list[EffectiveRule]) -> dict[str, EffectiveRule]:
    return {r.schema["key"]: r for r in rules}


# --- precedence -------------------------------------------------------


def test_program_default_flows_through_when_no_overrides() -> None:
    """No overrides → value is the program default, all flags false."""
    rules = get_effective_rules("income-calc", "conventional", {}, {})
    dti = _by_key(rules)["dtiLimit"]
    assert dti.value == 45  # conventional's dtiLimit
    assert dti.program_default == 45
    assert dti.org_value == 45
    assert dti.overridden is False
    assert dti.org_overridden is False
    assert dti.override is None


def test_org_override_wins_over_program_default() -> None:
    """Org override replaces program default; packet layer absent."""
    org: dict[str, dict[str, str | int | float | bool]] = {"conventional": {"dtiLimit": 50}}
    rules = get_effective_rules("income-calc", "conventional", {}, org)
    dti = _by_key(rules)["dtiLimit"]
    assert dti.value == 50
    assert dti.program_default == 45
    assert dti.org_value == 50
    assert dti.org_overridden is True
    assert dti.overridden is False


def test_packet_override_wins_over_org_override() -> None:
    """Packet override is the final say; org_value still reflects the
    layer beneath it so the UI can show "Org default: 50"."""
    org: dict[str, dict[str, str | int | float | bool]] = {"conventional": {"dtiLimit": 50}}
    packet: dict[str, dict[str, RuleOverride]] = {
        "income-calc": {
            "dtiLimit": {
                "value": 55,
                "reason": "strong compensating factors — 820 FICO, 12mo reserves",
                "overridden_at": datetime(2026, 4, 1, tzinfo=UTC),
                "overridden_by": "underwriter@example.com",
            }
        }
    }
    rules = get_effective_rules("income-calc", "conventional", packet, org)
    dti = _by_key(rules)["dtiLimit"]
    assert dti.value == 55
    assert dti.program_default == 45
    assert dti.org_value == 50
    assert dti.org_overridden is True
    assert dti.overridden is True
    assert dti.override is not None
    assert dti.override["reason"].startswith("strong compensating")


def test_packet_override_without_org_override_falls_back_to_program_default() -> None:
    """org_value == program_default when the org layer is silent, even
    though the packet layer is setting the final value."""
    packet: dict[str, dict[str, RuleOverride]] = {
        "income-calc": {
            "dtiLimit": {
                "value": 48,
                "reason": "borrower qualifies with bonus income",
                "overridden_at": datetime.now(UTC),
                "overridden_by": "u@example.com",
            }
        }
    }
    rules = get_effective_rules("income-calc", "conventional", packet, {})
    dti = _by_key(rules)["dtiLimit"]
    assert dti.value == 48
    assert dti.program_default == 45
    assert dti.org_value == 45  # no org override → falls to program default
    assert dti.org_overridden is False
    assert dti.overridden is True


def test_different_programs_yield_different_defaults() -> None:
    """FHA allows a looser DTI (50%) than Conventional (45%). Sanity
    check that the program switch is actually looked up, not hardcoded."""
    conv = _by_key(get_effective_rules("income-calc", "conventional", {}, {}))
    fha = _by_key(get_effective_rules("income-calc", "fha", {}, {}))
    assert conv["dtiLimit"].value == 45
    assert fha["dtiLimit"].value == 50
    # VA is the only program with residualIncome=True.
    va = _by_key(get_effective_rules("income-calc", "va", {}, {}))
    assert va["residualIncome"].value is True
    assert conv["residualIncome"].value is False


# --- unknown inputs ---------------------------------------------------


def test_unknown_app_returns_empty_list() -> None:
    """No schemas → no rules. This lets callers iterate unconditionally."""
    assert get_effective_rules("not-a-real-app", "conventional", {}, {}) == []


def test_unknown_program_leaves_defaults_none_but_keeps_schemas() -> None:
    """Every schema still returns an EffectiveRule, but program_default
    is None. Overrides still take precedence if provided."""
    org: dict[str, dict[str, str | int | float | bool]] = {"imaginary": {"dtiLimit": 99}}
    rules = _by_key(get_effective_rules("income-calc", "imaginary", {}, org))
    assert len(rules) == len(MICRO_APP_RULES["income-calc"])
    # Key not in org override → everything None.
    trending = rules["trendingMethod"]
    assert trending.program_default is None
    assert trending.org_value is None
    assert trending.value is None
    # Key in org override → org layer wins.
    dti = rules["dtiLimit"]
    assert dti.program_default is None
    assert dti.org_value == 99
    assert dti.value == 99


def test_title_exam_schema_keys_have_no_program_default() -> None:
    """`exceptionClassification` and `vestingSensitivity` are schema-only —
    no LoanProgramRules field backs them, matching the demo. The UI
    treats `value is None` as "customer admin must pick one"."""
    rules = _by_key(get_effective_rules("title-exam", "conventional", {}, {}))
    for key in ("exceptionClassification", "vestingSensitivity"):
        assert rules[key].program_default is None
        assert rules[key].value is None
        assert rules[key].org_overridden is False


# --- helpers ----------------------------------------------------------


def test_get_program_default_direct() -> None:
    assert get_program_default("conventional", "dtiLimit") == 45
    assert get_program_default("va", "residualIncome") is True
    assert get_program_default("conventional", "not-a-real-key") is None
    assert get_program_default("not-a-program", "dtiLimit") is None


def test_get_org_value_prefers_override() -> None:
    org: dict[str, dict[str, str | int | float | bool]] = {"conventional": {"dtiLimit": 50}}
    assert get_org_value("conventional", "dtiLimit", org) == 50
    # Unset rule falls through to program default.
    assert get_org_value("conventional", "chainDepth", org) == 30
    # Unset program still returns None.
    assert get_org_value("imaginary", "dtiLimit", org) is None


# --- format_rule_value ------------------------------------------------


def test_format_number_with_unit() -> None:
    schema_dti = MICRO_APP_RULES["income-calc"][0]  # dtiLimit
    assert schema_dti["key"] == "dtiLimit"
    assert format_rule_value(45, schema_dti) == "45 %"


def test_format_select_uses_option_label() -> None:
    schema_trend = next(s for s in MICRO_APP_RULES["income-calc"] if s["key"] == "trendingMethod")
    assert format_rule_value("averaged", schema_trend) == "Averaged (2-year average)"
    # Unknown value falls back to the raw string — keeps format_rule_value
    # total over the value domain even if the schema drifts.
    assert format_rule_value("custom-method", schema_trend) == "custom-method"


def test_format_toggle_renders_yes_no() -> None:
    schema_resid = next(s for s in MICRO_APP_RULES["income-calc"] if s["key"] == "residualIncome")
    assert format_rule_value(True, schema_resid) == "Yes"
    assert format_rule_value(False, schema_resid) == "No"


def test_format_none_value_renders_em_dash() -> None:
    """None means "no value set" (title-exam case). UI shows an em-dash
    placeholder so the row doesn't collapse."""
    schema_vesting = next(
        s for s in MICRO_APP_RULES["title-exam"] if s["key"] == "vestingSensitivity"
    )
    assert format_rule_value(None, schema_vesting) == "—"


# --- catalog integrity ------------------------------------------------


@pytest.mark.parametrize("program_id", list(LOAN_PROGRAMS.keys()))
def test_every_program_has_every_rule_field(program_id: str) -> None:
    """Spot-check that catalog entries aren't missing a field someone
    added to LoanProgramRules later — failing parametrize run is the
    first signal that a new field needs a value for every program."""
    program = LOAN_PROGRAMS[program_id]
    required = {
        "id",
        "label",
        "description",
        "confidenceThreshold",
        "chainDepth",
        "judgmentScope",
        "regulatoryFramework",
        "disclosureSet",
        "guidelines",
        "dtiLimit",
        "trendingMethod",
        "residualIncome",
    }
    missing = required - set(program.keys())
    assert not missing, f"{program_id} missing fields: {missing}"


@pytest.mark.parametrize("app_id", list(MICRO_APP_RULES.keys()))
def test_every_schema_has_required_fields(app_id: str) -> None:
    """Every schema carries at minimum (key, label, type). Selects must
    additionally carry `options`; numbers should carry min/max."""
    for schema in MICRO_APP_RULES[app_id]:
        assert "key" in schema
        assert "label" in schema
        assert "type" in schema
        if schema["type"] == "select":
            assert "options" in schema and len(schema["options"]) > 0
        if schema["type"] == "number":
            assert "min" in schema and "max" in schema
