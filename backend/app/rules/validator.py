"""Validate a (rule_key, value) pair against the rule catalog.

Two callers: the `/api/customer-admin/config` PUT endpoint (rejecting
bad client payloads before touching the DB) and the future packet-
override endpoints (same validation applies at both tiers). Keeps the
schema lookup + type checks in one place so future rule additions
only need to update `MICRO_APP_RULES` in catalog.py.

Errors are raised as `ValueError` so routers can wrap them in 400s
without this module having to depend on FastAPI.
"""

from __future__ import annotations

from app.rules.catalog import (
    MICRO_APP_RULES,
    EditableRuleSchema,
    RuleValue,
)


def find_schema(rule_key: str) -> EditableRuleSchema | None:
    """Return the first schema with this key across all apps, or None.

    Rule keys are (currently) unique across apps — each key identifies
    one field on LoanProgramRules. If two apps ever reference the same
    field, the schemas must agree on type/options so picking the first
    match is safe.
    """
    for schemas in MICRO_APP_RULES.values():
        for schema in schemas:
            if schema["key"] == rule_key:
                return schema
    return None


def validate_rule_value(rule_key: str, value: object) -> RuleValue:
    """Raise ValueError if `value` doesn't conform to the schema for
    `rule_key`. Returns the value (narrowed to `RuleValue`) on success.

    Splits the checks by schema type to keep error messages specific
    — a generic "invalid value" is useless in a validation failure
    surface that renders inline next to the field.
    """
    schema = find_schema(rule_key)
    if schema is None:
        raise ValueError(f"unknown rule key: {rule_key}")

    rule_type = schema["type"]

    if rule_type == "toggle":
        if not isinstance(value, bool):
            raise ValueError(f"{rule_key} expects a boolean (toggle), got {type(value).__name__}")
        return value

    if rule_type == "number":
        # JSON numbers arrive as int or float; bool is a subclass of int
        # in Python so we exclude it explicitly.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{rule_key} expects a number, got {type(value).__name__}")
        minimum = schema.get("min")
        maximum = schema.get("max")
        if minimum is not None and value < minimum:
            raise ValueError(f"{rule_key} must be ≥ {minimum} (got {value})")
        if maximum is not None and value > maximum:
            raise ValueError(f"{rule_key} must be ≤ {maximum} (got {value})")
        return value

    if rule_type == "select":
        if not isinstance(value, str):
            raise ValueError(f"{rule_key} expects a string (select), got {type(value).__name__}")
        allowed = {opt["value"] for opt in schema.get("options", [])}
        if value not in allowed:
            raise ValueError(f"{rule_key} must be one of {sorted(allowed)} (got {value!r})")
        return value

    # Should be unreachable — schema types are a Literal. Re-raise as a
    # ValueError so the router surfaces it as 400 rather than 500.
    raise ValueError(f"unsupported schema type for {rule_key}: {rule_type}")
