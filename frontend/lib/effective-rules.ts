/**
 * Client-side three-tier rule resolver — must stay in lockstep with
 * `backend/app/rules/resolver.py`. If outputs diverge, the pipeline
 * applies one value while the UI shows another (the exact failure mode
 * the ConfigApplied badge is supposed to prevent), so the tests for
 * both implementations exercise the same precedence cases.
 *
 * `packetOverrides` is kept in the signature for forward-compatibility
 * with US-4.3 (packet-level overrides ship with ECV in Step 4). Today
 * the Configuration page only needs the org tier.
 */

import {
  EditableRuleSchema,
  LOAN_PROGRAMS,
  MICRO_APP_RULES,
  OrgConfigOverrides,
  RuleValue,
} from "./rules";

export type RuleOverride = {
  value: RuleValue;
  reason: string;
  overriddenAt: string;
  overriddenBy: string;
};

export type PacketRuleOverrides = Record<string, Record<string, RuleOverride>>;

export type EffectiveRule = {
  schema: EditableRuleSchema;
  // `null` signals "no value anywhere" — title-exam's schema-only keys.
  value: RuleValue | null;
  overridden: boolean;
  override?: RuleOverride;
  orgOverridden: boolean;
  orgValue: RuleValue | null;
  programDefault: RuleValue | null;
};

/**
 * For a given micro-app, compute effective values by layering the three
 * levels: program default → org override → packet override.
 */
export function getEffectiveRules(
  microAppId: string,
  activeProgramId: string,
  packetOverrides: PacketRuleOverrides,
  orgOverrides: OrgConfigOverrides,
): EffectiveRule[] {
  const schemas = MICRO_APP_RULES[microAppId] || [];
  const program = LOAN_PROGRAMS[activeProgramId];
  const appPacket = packetOverrides[microAppId] || {};
  const programOrg = orgOverrides[activeProgramId] || {};

  return schemas.map((schema) => {
    const programDefault = program
      ? ((program as unknown as Record<string, RuleValue>)[schema.key] ?? null)
      : null;
    const hasOrgOverride = schema.key in programOrg;
    const orgValue: RuleValue | null = hasOrgOverride
      ? programOrg[schema.key]
      : programDefault;
    const packetOverride = appPacket[schema.key];
    const value: RuleValue | null = packetOverride
      ? packetOverride.value
      : orgValue;

    return {
      schema,
      value,
      overridden: Boolean(packetOverride),
      override: packetOverride,
      orgOverridden: hasOrgOverride,
      orgValue,
      programDefault,
    };
  });
}

/** Industry default for one rule on a program. `null` for unknowns. */
export function getProgramDefault(
  programId: string,
  ruleKey: string,
): RuleValue | null {
  const program = LOAN_PROGRAMS[programId];
  if (!program) return null;
  const v = (program as unknown as Record<string, RuleValue>)[ruleKey];
  return v === undefined ? null : v;
}

/** Org-level effective value (ignores packet overrides). */
export function getOrgValue(
  programId: string,
  ruleKey: string,
  orgOverrides: OrgConfigOverrides,
): RuleValue | null {
  const override = orgOverrides[programId]?.[ruleKey];
  if (override !== undefined) return override;
  return getProgramDefault(programId, ruleKey);
}

/** Format a rule value using its schema — same output as the Python twin. */
export function formatRuleValue(
  value: RuleValue | null,
  schema: EditableRuleSchema,
): string {
  if (value === null || value === undefined) return "—";
  if (schema.type === "toggle") return value ? "Yes" : "No";
  if (schema.type === "select") {
    const opt = schema.options?.find((o) => o.value === value);
    return opt?.label ?? String(value);
  }
  if (schema.type === "number") {
    return schema.unit ? `${value} ${schema.unit}` : String(value);
  }
  return String(value);
}
