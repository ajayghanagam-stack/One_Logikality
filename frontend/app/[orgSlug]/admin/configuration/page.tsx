"use client";

/**
 * Customer-admin Configuration page (US-4.2 / US-4.7).
 *
 * Three-tier rule system surface: industry defaults → org overrides →
 * (later) packet overrides. This page edits the middle tier. Layout and
 * copy mirror the `one-logikality-demo` reference so the two products
 * keep visual parity.
 *
 * Server endpoints:
 *   GET    /api/customer-admin/config              — load all org overrides
 *   PUT    /api/customer-admin/config/{program_id} — replace-all save
 *   DELETE /api/customer-admin/config/{program_id} — reset program to defaults
 *
 * Save semantics: we strip values equal to the industry default before
 * PUT so we never persist a redundant override row.
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";
import {
  LOAN_PROGRAMS,
  MICRO_APP_RULES,
  OrgConfigOverrides,
  RULE_APP_ICONS,
  RULE_APP_IDS,
  RULE_APP_LABELS,
  RuleValue,
  type EditableRuleSchema,
  type LoanProgramRules,
} from "@/lib/rules";
import { formatRuleValue, getOrgValue } from "@/lib/effective-rules";

type ConfigResponse = { overrides: OrgConfigOverrides };

type DraftState = Record<string, RuleValue>;

export default function CustomerAdminConfigurationPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const { ready } = useRequireRole(["customer_admin"], `/${orgSlug}`);
  const { token } = useAuth();

  const [orgOverrides, setOrgOverrides] = useState<OrgConfigOverrides | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [activeProgramId, setActiveProgramId] = useState<string>("conventional");
  const [expandedApp, setExpandedApp] = useState<string | null>("compliance");
  const [drafts, setDrafts] = useState<DraftState>({});
  const [showSavedToast, setShowSavedToast] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api<ConfigResponse>("/api/customer-admin/config", { token });
        if (cancelled) return;
        setOrgOverrides(data.overrides);
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.detail ?? `Request failed (${err.status}).`
            : "Could not load configuration. Please try again.";
        setLoadError(msg);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token]);

  if (!ready) return null;

  const program: LoanProgramRules = LOAN_PROGRAMS[activeProgramId];

  const getSavedValue = (ruleKey: string): RuleValue | null => {
    if (!orgOverrides) return null;
    return getOrgValue(activeProgramId, ruleKey, orgOverrides);
  };

  const getCurrentValue = (ruleKey: string): RuleValue | null => {
    if (drafts[ruleKey] !== undefined) return drafts[ruleKey];
    return getSavedValue(ruleKey);
  };

  const getIndustryDefault = (ruleKey: string): RuleValue | null => {
    const v = (program as unknown as Record<string, RuleValue>)[ruleKey];
    return v === undefined ? null : v;
  };

  const pendingChanges = Object.keys(drafts).filter(
    (k) => drafts[k] !== getSavedValue(k),
  );
  const hasPendingChanges = pendingChanges.length > 0;
  const programHasOrgOverrides =
    !!orgOverrides &&
    Object.keys(orgOverrides[activeProgramId] ?? {}).length > 0;

  const dtiDraft = drafts.dtiLimit;
  const dtiWarning =
    typeof dtiDraft === "number" && dtiDraft > 50
      ? `DTI limit ${dtiDraft}% exceeds the industry standard of ${program.dtiLimit}% for ${program.label} loans. This increases risk exposure.`
      : null;

  function updateDraft(ruleKey: string, value: RuleValue) {
    setDrafts((prev) => {
      const next = { ...prev, [ruleKey]: value };
      if (value === getSavedValue(ruleKey)) delete next[ruleKey];
      return next;
    });
  }

  async function handleSave() {
    if (!token || !orgOverrides || !hasPendingChanges) return;
    setSaving(true);
    setSaveError(null);

    // Start from the server's current program overrides; apply drafts;
    // then strip values that equal the industry default so we don't
    // persist redundant rows.
    const merged: Record<string, RuleValue> = {
      ...(orgOverrides[activeProgramId] ?? {}),
    };
    for (const key of Object.keys(drafts)) {
      merged[key] = drafts[key];
    }
    const filtered: Record<string, RuleValue> = {};
    for (const [k, v] of Object.entries(merged)) {
      if (v !== getIndustryDefault(k)) filtered[k] = v;
    }

    try {
      const data = await api<ConfigResponse>(
        `/api/customer-admin/config/${activeProgramId}`,
        { method: "PUT", token, json: { overrides: filtered } },
      );
      setOrgOverrides(data.overrides);
      setDrafts({});
      setShowSavedToast(true);
      setTimeout(() => setShowSavedToast(false), 2500);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not save changes. Please try again.";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }

  function handleDiscard() {
    setDrafts({});
  }

  async function handleResetRule(ruleKey: string) {
    if (!token || !orgOverrides) return;
    // Clear any draft for this rule first.
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[ruleKey];
      return next;
    });
    // If the rule isn't stored as an override, there's nothing to persist.
    const stored = orgOverrides[activeProgramId] ?? {};
    if (!(ruleKey in stored)) return;

    const filtered: Record<string, RuleValue> = {};
    for (const [k, v] of Object.entries(stored)) {
      if (k !== ruleKey) filtered[k] = v;
    }
    try {
      const data = await api<ConfigResponse>(
        `/api/customer-admin/config/${activeProgramId}`,
        { method: "PUT", token, json: { overrides: filtered } },
      );
      setOrgOverrides(data.overrides);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not reset rule. Please try again.";
      setSaveError(msg);
    }
  }

  async function handleResetProgram() {
    if (!token) return;
    try {
      const data = await api<ConfigResponse>(
        `/api/customer-admin/config/${activeProgramId}`,
        { method: "DELETE", token },
      );
      setOrgOverrides(data.overrides);
      setDrafts({});
      setShowResetConfirm(false);
      setShowSavedToast(true);
      setTimeout(() => setShowSavedToast(false), 2500);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not reset program. Please try again.";
      setSaveError(msg);
    }
  }

  function countEditedForApp(appId: string): number {
    const rulesForApp = MICRO_APP_RULES[appId] ?? [];
    return rulesForApp.filter((r) => {
      const industryDefault = getIndustryDefault(r.key);
      return getCurrentValue(r.key) !== industryDefault;
    }).length;
  }

  return (
    <div style={{ paddingBottom: hasPendingChanges ? 88 : 0 }}>
      <nav style={breadcrumbStyle} aria-label="Breadcrumb">
        <span>Administration</span>
        <span style={{ color: chrome.mutedFg }}>›</span>
        <span style={{ color: chrome.charcoal, fontWeight: 500 }}>Configuration</span>
      </nav>

      <div style={{ maxWidth: 960 }}>
        <header style={headerRowStyle}>
          <div>
            <h1 style={titleStyle}>Organization configuration</h1>
            <p style={subtitleStyle}>
              Customize default rule sets for each loan program. These
              defaults apply to every packet processed by your
              organization. Individual packets can still override them at
              processing time.
            </p>
          </div>
          {showSavedToast ? (
            <div style={savedToastStyle} role="status">
              <CheckIcon /> Changes saved
            </div>
          ) : null}
        </header>

        {loadError ? (
          <div role="alert" style={pageErrorStyle}>{loadError}</div>
        ) : null}
        {saveError ? (
          <div role="alert" style={pageErrorStyle}>{saveError}</div>
        ) : null}

        {orgOverrides === null && !loadError ? (
          <div style={emptyStyle}>Loading configuration…</div>
        ) : null}

        {orgOverrides !== null ? (
          <>
            <IndustryStandardsNotice />

            <ProgramTabBar
              activeProgramId={activeProgramId}
              orgOverrides={orgOverrides}
              onSelect={(id) => {
                if (id === activeProgramId) return;
                if (
                  hasPendingChanges &&
                  !confirm(
                    "You have unsaved changes. Discard them and switch programs?",
                  )
                ) {
                  return;
                }
                // Saved/industry baselines differ per program — carrying
                // a half-edited draft across tabs would misrepresent
                // "dirty" vs "saved" on the new tab.
                setDrafts({});
                setShowResetConfirm(false);
                setActiveProgramId(id);
              }}
            />

            <ActiveProgramCard
              program={program}
              canReset={programHasOrgOverrides}
              confirming={showResetConfirm}
              onAskReset={() => setShowResetConfirm(true)}
              onCancelReset={() => setShowResetConfirm(false)}
              onConfirmReset={handleResetProgram}
            />

            {dtiWarning ? <DtiWarning message={dtiWarning} /> : null}

            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {RULE_APP_IDS.map((appId) => {
                const rules = MICRO_APP_RULES[appId] ?? [];
                const isExpanded = expandedApp === appId;
                const editedCount = countEditedForApp(appId);

                return (
                  <div
                    key={appId}
                    style={{
                      ...accordionCardStyle,
                      border: `1px solid ${
                        editedCount > 0 ? chrome.amberLight : chrome.border
                      }`,
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => setExpandedApp(isExpanded ? null : appId)}
                      style={{
                        ...accordionHeaderStyle,
                        background: isExpanded ? chrome.amberBg : chrome.card,
                        borderBottom: isExpanded
                          ? `1px solid ${chrome.amberLight}`
                          : "none",
                      }}
                    >
                      <span style={{ fontSize: 20 }} aria-hidden="true">
                        {RULE_APP_ICONS[appId]}
                      </span>
                      <div style={{ flex: 1, textAlign: "left" }}>
                        <div style={accordionTitleStyle}>
                          {RULE_APP_LABELS[appId]}
                          {editedCount > 0 ? (
                            <span style={editedPillStyle}>
                              {editedCount} edited
                            </span>
                          ) : null}
                        </div>
                        <div style={accordionSubtitleStyle}>
                          {rules.length} configurable rule
                          {rules.length === 1 ? "" : "s"} for {program.label}
                        </div>
                      </div>
                      <Chevron open={isExpanded} />
                    </button>

                    {isExpanded ? (
                      <div style={{ padding: "16px 20px" }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                          {rules.map((schema) => (
                            <RuleRow
                              key={schema.key}
                              schema={schema}
                              currentValue={getCurrentValue(schema.key)}
                              savedValue={getSavedValue(schema.key)}
                              industryDefault={getIndustryDefault(schema.key)}
                              isDirty={
                                drafts[schema.key] !== undefined &&
                                drafts[schema.key] !== getSavedValue(schema.key)
                              }
                              onChange={(v) => updateDraft(schema.key, v)}
                              onReset={() => handleResetRule(schema.key)}
                            />
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </>
        ) : null}
      </div>

      {hasPendingChanges ? (
        <StickySaveBar
          count={pendingChanges.length}
          programLabel={program.label}
          saving={saving}
          onDiscard={handleDiscard}
          onSave={handleSave}
        />
      ) : null}
    </div>
  );
}

/* ----- subcomponents ------------------------------------------------- */

function IndustryStandardsNotice() {
  return (
    <div style={industryNoticeStyle}>
      <div style={industryNoticeIconStyle}>
        <CheckIcon />
      </div>
      <div style={{ flex: 1, fontSize: 12, color: "#065F46", lineHeight: 1.55 }}>
        <div style={{ fontWeight: 700, marginBottom: 2 }}>
          Industry-standard defaults are pre-applied
        </div>
        <div>
          Most organizations proceed with defaults (GSE, HUD, VA, USDA,
          ALTA standards). Customize only if your organization applies
          specific investor overlays or policies stricter than industry
          standard.
        </div>
      </div>
    </div>
  );
}

function ProgramTabBar({
  activeProgramId,
  orgOverrides,
  onSelect,
}: {
  activeProgramId: string;
  orgOverrides: OrgConfigOverrides;
  onSelect: (id: string) => void;
}) {
  return (
    <div style={tabBarStyle} role="tablist">
      {Object.values(LOAN_PROGRAMS).map((p) => {
        const active = activeProgramId === p.id;
        const hasOverrides = Object.keys(orgOverrides[p.id] ?? {}).length > 0;
        return (
          <button
            key={p.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onSelect(p.id)}
            style={{
              ...tabButtonStyle,
              fontWeight: active ? 700 : 500,
              background: active ? chrome.card : "transparent",
              color: active ? chrome.amberDark : chrome.mutedFg,
              boxShadow: active ? "0 1px 3px rgba(20,18,14,0.08)" : "none",
            }}
          >
            {p.label}
            {hasOverrides ? <span style={tabDotStyle} aria-hidden="true" /> : null}
          </button>
        );
      })}
    </div>
  );
}

function ActiveProgramCard({
  program,
  canReset,
  confirming,
  onAskReset,
  onCancelReset,
  onConfirmReset,
}: {
  program: LoanProgramRules;
  canReset: boolean;
  confirming: boolean;
  onAskReset: () => void;
  onCancelReset: () => void;
  onConfirmReset: () => void;
}) {
  return (
    <div style={programCardStyle}>
      <span style={{ fontSize: 14 }} aria-hidden="true">✦</span>
      <div style={{ flex: 1, fontSize: 12, color: chrome.amberDark, lineHeight: 1.5 }}>
        <span style={{ fontWeight: 700 }}>{program.label}:</span>{" "}
        <span>{program.description}</span>
      </div>
      {canReset ? (
        confirming ? (
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "#B91C1C", fontWeight: 600 }}>
              Reset all overrides for {program.label}?
            </span>
            <button type="button" onClick={onConfirmReset} style={resetDangerBtnStyle}>
              Yes, reset
            </button>
            <button type="button" onClick={onCancelReset} style={resetCancelBtnStyle}>
              Cancel
            </button>
          </div>
        ) : (
          <button type="button" onClick={onAskReset} style={resetProgramBtnStyle}>
            Reset program to defaults
          </button>
        )
      ) : null}
    </div>
  );
}

function DtiWarning({ message }: { message: string }) {
  return (
    <div style={dtiWarningStyle} role="alert">
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ flexShrink: 0, marginTop: 1 }}
      >
        <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
      <div style={{ flex: 1, lineHeight: 1.5 }}>
        <span style={{ fontWeight: 700 }}>Elevated risk:</span> {message}
      </div>
    </div>
  );
}

function RuleRow({
  schema,
  currentValue,
  savedValue,
  industryDefault,
  isDirty,
  onChange,
  onReset,
}: {
  schema: EditableRuleSchema;
  currentValue: RuleValue | null;
  savedValue: RuleValue | null;
  industryDefault: RuleValue | null;
  isDirty: boolean;
  onChange: (value: RuleValue) => void;
  onReset: () => void;
}) {
  const isOrgOverridden = savedValue !== industryDefault;
  const differsFromIndustry = currentValue !== industryDefault;

  return (
    <div
      style={{
        ...ruleRowStyle,
        border: `1px solid ${differsFromIndustry ? chrome.amberLight : chrome.border}`,
        background: differsFromIndustry ? chrome.amberBg : chrome.card,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: chrome.charcoal }}>
              {schema.label}
            </span>
            {isOrgOverridden && !isDirty ? (
              <span style={customizedPillStyle}>Customized</span>
            ) : null}
            {isDirty ? <span style={unsavedPillStyle}>Unsaved</span> : null}
          </div>
          {schema.helpText ? (
            <div style={{ fontSize: 11, color: chrome.mutedFg, lineHeight: 1.5 }}>
              {schema.helpText}
            </div>
          ) : null}
        </div>
        {differsFromIndustry ? (
          <button type="button" onClick={onReset} style={resetRuleBtnStyle}>
            Reset to default
          </button>
        ) : null}
      </div>

      {schema.type === "number" ? (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <input
            type="number"
            value={typeof currentValue === "number" ? currentValue : ""}
            min={schema.min}
            max={schema.max}
            onChange={(e) => onChange(Number(e.target.value))}
            style={numberInputStyle}
          />
          {schema.unit ? (
            <span style={{ fontSize: 12, color: chrome.mutedFg, fontWeight: 500 }}>
              {schema.unit}
            </span>
          ) : null}
          {differsFromIndustry ? (
            <span style={{ fontSize: 11, color: chrome.mutedFg, marginLeft: "auto" }}>
              Industry default:{" "}
              <strong>{formatRuleValue(industryDefault, schema)}</strong>
            </span>
          ) : null}
        </div>
      ) : null}

      {schema.type === "select" ? (
        <div>
          <select
            value={typeof currentValue === "string" ? currentValue : ""}
            onChange={(e) => onChange(e.target.value)}
            style={selectInputStyle}
          >
            {schema.options?.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          {differsFromIndustry ? (
            <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 5 }}>
              Industry default:{" "}
              <strong>{formatRuleValue(industryDefault, schema)}</strong>
            </div>
          ) : null}
        </div>
      ) : null}

      {schema.type === "toggle" ? (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={!!currentValue}
              onChange={(e) => onChange(e.target.checked)}
              style={{ width: 16, height: 16, cursor: "pointer" }}
            />
            <span style={{ fontSize: 13, color: chrome.charcoal, fontWeight: 500 }}>
              {currentValue ? "Required" : "Not required"}
            </span>
          </label>
          {differsFromIndustry ? (
            <span style={{ fontSize: 11, color: chrome.mutedFg, marginLeft: "auto" }}>
              Industry default:{" "}
              <strong>{industryDefault ? "Required" : "Not required"}</strong>
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function StickySaveBar({
  count,
  programLabel,
  saving,
  onDiscard,
  onSave,
}: {
  count: number;
  programLabel: string;
  saving: boolean;
  onDiscard: () => void;
  onSave: () => void;
}) {
  return (
    <div style={stickyBarStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={stickyBarIconStyle}>
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 9v4M12 17.01l.01 0M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
        </div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: chrome.charcoal }}>
            {count} unsaved change{count === 1 ? "" : "s"}
          </div>
          <div style={{ fontSize: 11, color: chrome.mutedFg }}>
            For {programLabel} loan program
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          onClick={onDiscard}
          disabled={saving}
          style={discardBtnStyle}
        >
          Discard
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          style={{ ...saveBtnStyle, opacity: saving ? 0.7 : 1 }}
        >
          {saving ? "Saving…" : `Save ${count} change${count === 1 ? "" : "s"}`}
        </button>
      </div>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke={chrome.mutedFg}
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ transform: open ? "rotate(180deg)" : "rotate(0)", transition: "transform 0.2s" }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

/* ----- styles -------------------------------------------------------- */

const breadcrumbStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginBottom: 16,
  fontSize: 12,
  color: chrome.mutedFg,
};

const headerRowStyle: React.CSSProperties = {
  marginBottom: 18,
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 16,
};

const titleStyle: React.CSSProperties = {
  fontSize: 24,
  fontWeight: typography.fontWeight.headline,
  margin: "0 0 4px",
  color: chrome.charcoal,
  letterSpacing: "-0.02em",
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 13,
  color: chrome.mutedFg,
  margin: 0,
  maxWidth: 640,
  lineHeight: 1.5,
};

const savedToastStyle: React.CSSProperties = {
  padding: "8px 14px",
  background: "#D1FAE5",
  border: "1px solid #A7F3D0",
  borderRadius: 8,
  fontSize: 12,
  fontWeight: 600,
  color: "#065F46",
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const pageErrorStyle: React.CSSProperties = {
  background: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  padding: "8px 12px",
  fontSize: 12,
  marginBottom: 12,
};

const emptyStyle: React.CSSProperties = {
  padding: "30px 20px",
  textAlign: "center",
  color: chrome.mutedFg,
  fontSize: 13,
};

const industryNoticeStyle: React.CSSProperties = {
  padding: "12px 16px",
  background: "#F0FDF4",
  border: "1px solid #A7F3D0",
  borderRadius: 8,
  marginBottom: 18,
  display: "flex",
  alignItems: "flex-start",
  gap: 12,
};

const industryNoticeIconStyle: React.CSSProperties = {
  width: 26,
  height: 26,
  borderRadius: 7,
  flexShrink: 0,
  background: "#D1FAE5",
  border: "1px solid #A7F3D0",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "#059669",
};

const tabBarStyle: React.CSSProperties = {
  display: "flex",
  gap: 4,
  background: chrome.muted,
  borderRadius: 10,
  padding: 4,
  marginBottom: 18,
  overflow: "auto",
};

const tabButtonStyle: React.CSSProperties = {
  padding: "8px 14px",
  fontSize: 12,
  border: "none",
  borderRadius: 7,
  cursor: "pointer",
  whiteSpace: "nowrap",
  transition: "all 0.15s",
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  fontFamily: typography.fontFamily.primary,
};

const tabDotStyle: React.CSSProperties = {
  width: 5,
  height: 5,
  borderRadius: "50%",
  background: chrome.amber,
};

const programCardStyle: React.CSSProperties = {
  padding: "12px 16px",
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  borderRadius: 8,
  marginBottom: 16,
  display: "flex",
  alignItems: "center",
  gap: 12,
  flexWrap: "wrap",
};

const resetProgramBtnStyle: React.CSSProperties = {
  padding: "5px 12px",
  fontSize: 11,
  fontWeight: 600,
  background: "#fff",
  color: "#B91C1C",
  border: "1px solid #FCA5A5",
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const resetDangerBtnStyle: React.CSSProperties = {
  padding: "5px 10px",
  fontSize: 11,
  fontWeight: 600,
  background: "#B91C1C",
  color: "#fff",
  border: "none",
  borderRadius: 5,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const resetCancelBtnStyle: React.CSSProperties = {
  padding: "5px 10px",
  fontSize: 11,
  fontWeight: 600,
  background: "#fff",
  color: chrome.mutedFg,
  border: `1px solid ${chrome.border}`,
  borderRadius: 5,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const dtiWarningStyle: React.CSSProperties = {
  padding: "12px 14px",
  background: "#FEF3C7",
  border: "1px solid #FCD34D",
  borderRadius: 8,
  marginBottom: 16,
  fontSize: 12,
  color: "#78350F",
  display: "flex",
  alignItems: "flex-start",
  gap: 10,
};

const accordionCardStyle: React.CSSProperties = {
  background: chrome.card,
  borderRadius: 12,
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
  overflow: "hidden",
};

const accordionHeaderStyle: React.CSSProperties = {
  width: "100%",
  padding: "14px 20px",
  border: "none",
  display: "flex",
  alignItems: "center",
  gap: 12,
  cursor: "pointer",
  textAlign: "left",
  transition: "background 0.15s",
  fontFamily: typography.fontFamily.primary,
};

const accordionTitleStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.charcoal,
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const accordionSubtitleStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
  marginTop: 1,
};

const editedPillStyle: React.CSSProperties = {
  fontSize: 9,
  fontWeight: 700,
  padding: "1px 7px",
  borderRadius: 10,
  background: "#FEF3C7",
  color: "#78350F",
  border: "1px solid #FCD34D",
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const customizedPillStyle: React.CSSProperties = {
  fontSize: 9,
  fontWeight: 700,
  padding: "1px 7px",
  borderRadius: 10,
  background: "#FEF3C7",
  color: "#78350F",
  border: "1px solid #FCD34D",
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const unsavedPillStyle: React.CSSProperties = {
  fontSize: 9,
  fontWeight: 700,
  padding: "1px 7px",
  borderRadius: 10,
  background: "#DBEAFE",
  color: "#1E40AF",
  border: "1px solid #93C5FD",
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const ruleRowStyle: React.CSSProperties = {
  padding: "14px 16px",
  borderRadius: 9,
};

const resetRuleBtnStyle: React.CSSProperties = {
  padding: "3px 10px",
  fontSize: 10,
  fontWeight: 600,
  background: "transparent",
  color: "#B91C1C",
  border: "none",
  cursor: "pointer",
  whiteSpace: "nowrap",
  fontFamily: typography.fontFamily.primary,
};

const numberInputStyle: React.CSSProperties = {
  width: 120,
  padding: "8px 12px",
  fontSize: 13,
  border: `1px solid ${chrome.border}`,
  borderRadius: 6,
  background: "#fff",
  color: chrome.charcoal,
  fontFamily: typography.fontFamily.primary,
};

const selectInputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 12px",
  fontSize: 13,
  border: `1px solid ${chrome.border}`,
  borderRadius: 6,
  background: "#fff",
  color: chrome.charcoal,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const stickyBarStyle: React.CSSProperties = {
  position: "fixed",
  bottom: 0,
  left: 240,
  right: 0,
  background: "#fff",
  borderTop: `1px solid ${chrome.border}`,
  boxShadow: "0 -4px 16px rgba(20,18,14,0.08)",
  padding: "14px 32px",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  zIndex: 50,
};

const stickyBarIconStyle: React.CSSProperties = {
  width: 26,
  height: 26,
  borderRadius: 8,
  background: "#DBEAFE",
  border: "1px solid #93C5FD",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "#1E40AF",
};

const discardBtnStyle: React.CSSProperties = {
  padding: "9px 16px",
  fontSize: 13,
  fontWeight: 600,
  background: "#fff",
  color: chrome.charcoal,
  border: `1px solid ${chrome.border}`,
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const saveBtnStyle: React.CSSProperties = {
  padding: "9px 22px",
  fontSize: 13,
  fontWeight: 600,
  background: chrome.amber,
  color: "#fff",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};
