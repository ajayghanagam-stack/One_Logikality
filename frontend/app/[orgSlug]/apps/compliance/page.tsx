"use client";

/**
 * Compliance micro-app page (US-6.3).
 *
 * Five tabs matching the one-logikality-demo reference 1:1:
 *  - Overview — summary bullets + KPI cards (score / passed / failed / warn / n/a)
 *  - Disclosures — required disclosure checklist (federal + IL state)
 *  - Fee Tolerances — TRID bucket table (LE vs CD) from server
 *  - Violations — expandable fail/warn rows with inline AI note + MISMO panel
 *  - Audit Report — PDF/MISMO XML export surface
 *
 * Data source: GET /api/packets/{id}/compliance. The ECV launcher
 * routes here when the org is subscribed+enabled AND compliance is
 * `ready` (all required MISMO docs found). Server re-checks the
 * subscription so a deep link can't bypass gating.
 */

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

/* ----- types ---------------------------------------------------------- */

type CheckStatus = "pass" | "fail" | "warn" | "n/a";
type ToleranceStatus = "pass" | "fail" | "warn";

type MismoField = {
  entity: string;
  field: string;
  value: string;
  confidence: number;
};

type ComplianceCheck = {
  id: string;
  check_code: string;
  category: string;
  rule: string;
  status: CheckStatus;
  detail: string;
  ai_note: string | null;
  mismo: MismoField[];
};

type FeeTolerance = {
  id: string;
  bucket: string;
  le: string;
  cd: string;
  diff: string;
  pct: string;
  status: ToleranceStatus;
};

type ComplianceSummary = {
  total_checks: number;
  passed: number;
  failed: number;
  warned: number;
  not_applicable: number;
  score: number;
};

type ComplianceDashboard = {
  summary: ComplianceSummary;
  checks: ComplianceCheck[];
  fee_tolerances: FeeTolerance[];
};

type Tab = "overview" | "disclosures" | "tolerances" | "violations" | "audit";

/* ----- palette (aligned with the ECV page constants) ------------------ */

const SUCCESS = "#10B981";
const SUCCESS_BG = "#D1FAE5";
const DESTRUCTIVE = "#DC2626";
const DESTRUCTIVE_BG = "#FEE2E2";

function statusStyle(s: CheckStatus | ToleranceStatus) {
  if (s === "pass") return { color: SUCCESS, bg: SUCCESS_BG, label: "PASS" };
  if (s === "fail") return { color: DESTRUCTIVE, bg: DESTRUCTIVE_BG, label: "FAIL" };
  if (s === "warn") return { color: chrome.amberDark, bg: chrome.amberBg, label: "WARN" };
  return { color: chrome.mutedFg, bg: chrome.muted, label: "N/A" };
}

/* ----- page ----------------------------------------------------------- */

export default function CompliancePage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const searchParams = useSearchParams();
  const packetId = searchParams.get("packet");
  const router = useRouter();
  const { ready } = useRequireRole(["customer_admin", "customer_user"], `/${orgSlug}`);
  const { token } = useAuth();

  const [data, setData] = useState<ComplianceDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token || !packetId) return;
    let cancelled = false;
    (async () => {
      try {
        const payload = await api<ComplianceDashboard>(
          `/api/packets/${packetId}/compliance`,
          { token },
        );
        if (!cancelled) setData(payload);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          setError("The Compliance app is not enabled for your organization.");
        } else if (err instanceof ApiError && err.status === 409) {
          setError("Compliance findings are still being computed. Check back shortly.");
        } else if (err instanceof ApiError && err.status === 404) {
          setError("Packet not found.");
        } else {
          setError("Couldn't load compliance results.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token, packetId]);

  if (!ready) return null;

  if (!packetId) {
    return (
      <div style={{ maxWidth: 800 }}>
        <h1 style={titleStyle}>Compliance</h1>
        <p style={emptyStyle}>
          Open a packet from the ECV dashboard to run compliance analysis.
        </p>
        <Link href={`/${orgSlug}/upload`} style={linkBtnStyle}>
          Upload a packet
        </Link>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: 800 }}>
        <h1 style={titleStyle}>Compliance</h1>
        <div role="alert" style={errorBoxStyle}>
          {error}
        </div>
        <div style={{ marginTop: 16 }}>
          <button
            type="button"
            onClick={() => router.push(`/${orgSlug}/ecv?packet=${packetId}`)}
            style={linkBtnStyle}
          >
            Back to ECV dashboard
          </button>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ maxWidth: 800 }}>
        <h1 style={titleStyle}>Compliance</h1>
        <p style={emptyStyle}>Loading…</p>
      </div>
    );
  }

  return <Dashboard data={data} orgSlug={orgSlug} packetId={packetId} />;
}

/* ----- dashboard ------------------------------------------------------ */

function Dashboard({
  data,
  orgSlug,
  packetId,
}: {
  data: ComplianceDashboard;
  orgSlug: string;
  packetId: string;
}) {
  const { summary, checks, fee_tolerances: tolerances } = data;
  const [tab, setTab] = useState<Tab>("overview");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const violations = checks.filter((c) => c.status === "fail" || c.status === "warn");
  const scoreColor =
    summary.score >= 80 ? SUCCESS : summary.score >= 60 ? chrome.amberDark : DESTRUCTIVE;
  const scoreBg =
    summary.score >= 80 ? SUCCESS_BG : summary.score >= 60 ? chrome.amberBg : DESTRUCTIVE_BG;
  const scoreLabel =
    summary.score >= 80
      ? "Compliant"
      : summary.score >= 60
        ? "Needs review"
        : "Non-compliant";

  return (
    <div style={{ fontFamily: typography.fontFamily.primary }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 20,
        }}
      >
        <div>
          <h1 style={{ ...titleStyle, margin: "0 0 6px" }}>Regulatory compliance analysis</h1>
          <div style={{ display: "flex", gap: 16, fontSize: 12, color: chrome.mutedFg }}>
            <span>
              Packet:{" "}
              <strong style={{ color: chrome.charcoal, fontFamily: "monospace" }}>
                {packetId.slice(0, 8)}
              </strong>
            </span>
            <span>
              Framework:{" "}
              <strong style={{ color: chrome.charcoal }}>CFPB 2026</strong>
            </span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href={`/${orgSlug}/ecv?packet=${packetId}`} style={secondaryBtnStyle}>
            Back to ECV
          </Link>
          <button type="button" style={ctaBtnStyle} onClick={() => setTab("audit")}>
            Export report
          </button>
        </div>
      </div>

      {/* Tab strip */}
      <div
        style={{
          display: "flex",
          gap: 0,
          borderBottom: `2px solid ${chrome.border}`,
          marginBottom: 20,
        }}
      >
        {(
          [
            { key: "overview", label: "Overview" },
            { key: "disclosures", label: "Disclosures" },
            { key: "tolerances", label: "Fee Tolerances" },
            {
              key: "violations",
              label: `Violations (${summary.failed + summary.warned})`,
            },
            { key: "audit", label: "Audit Report" },
          ] as { key: Tab; label: string }[]
        ).map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              style={{
                padding: "10px 18px",
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                border: "none",
                background: "none",
                cursor: "pointer",
                color: active ? chrome.amberDark : chrome.mutedFg,
                borderBottom: active
                  ? `2px solid ${chrome.amberDark}`
                  : "2px solid transparent",
                marginBottom: -2,
                fontFamily: typography.fontFamily.primary,
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === "overview" && (
        <OverviewTab
          summary={summary}
          scoreColor={scoreColor}
          scoreBg={scoreBg}
          scoreLabel={scoreLabel}
          onGoTolerances={() => setTab("tolerances")}
          onGoAudit={() => setTab("audit")}
          onGoViolations={() => setTab("violations")}
        />
      )}
      {tab === "disclosures" && <DisclosuresTab />}
      {tab === "tolerances" && <ToleranceTab rows={tolerances} />}
      {tab === "violations" && (
        <ViolationsTab
          violations={violations}
          expandedId={expandedId}
          onToggle={(id) => setExpandedId((prev) => (prev === id ? null : id))}
          failed={summary.failed}
          warned={summary.warned}
        />
      )}
      {tab === "audit" && <AuditTab summary={summary} />}
    </div>
  );
}

/* ----- Overview ------------------------------------------------------- */

function OverviewTab({
  summary,
  scoreColor,
  scoreBg,
  scoreLabel,
  onGoTolerances,
  onGoAudit,
  onGoViolations,
}: {
  summary: ComplianceSummary;
  scoreColor: string;
  scoreBg: string;
  scoreLabel: string;
  onGoTolerances: () => void;
  onGoAudit: () => void;
  onGoViolations: () => void;
}) {
  // Bullets mirror the demo's narrative on the Overview tab — ported
  // verbatim so the reviewer briefing reads the same on both products.
  const bullets = [
    `Loan file passes ${summary.passed} of ${summary.total_checks} regulatory compliance checks under the CFPB 2026 framework.`,
    "TRID Closing Disclosure delivery timing (CD delivered only 2 business days before closing) and missing Illinois Radon disclosure are the two open violations.",
    "Fee tolerance analysis shows all closing costs within TRID limits. The 10% bucket is at 8.4% — approaching but within the 10% threshold.",
    "RESPA, ECOA, and HMDA checks all pass. Right of rescission is not applicable (purchase transaction).",
    "Recommended next step: obtain Illinois Radon disclosure and document CD delivery date before proceeding to closing.",
  ];

  return (
    <div>
      {/* ConfigApplied placeholder (US-4.5) — visual pill so reviewers
          know which rule set the verdict was computed under. Wires to
          the real ConfigApplied component when that slice lands. */}
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 16,
          padding: "6px 12px",
          borderRadius: 20,
          fontSize: 11,
          fontWeight: 600,
          color: chrome.amberDark,
          background: chrome.amberBg,
          border: `1px solid ${chrome.amberLight}`,
        }}
      >
        <span style={{ fontSize: 10 }}>⚙</span>
        Rules applied: CFPB 2026 framework · Industry defaults
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)",
          gap: 20,
          marginBottom: 20,
          alignItems: "flex-start",
        }}
      >
        <div style={{ ...cardStyle, padding: "28px 32px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 18,
            }}
          >
            <span style={{ fontSize: 16, color: chrome.amberDark }}>✦</span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: chrome.mutedFg,
                letterSpacing: 1,
                textTransform: "uppercase",
              }}
            >
              Compliance summary
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {bullets.map((point, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  fontSize: 14,
                  color: chrome.charcoal,
                  lineHeight: 1.65,
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: chrome.amberDark,
                    marginTop: 8,
                    flexShrink: 0,
                  }}
                />
                <span>{point}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <KpiCard
            label="Compliance score"
            sub={scoreLabel}
            value={`${summary.score}%`}
            color={scoreColor}
            bg={scoreBg}
            large
          />
          <KpiCard
            label="Passed"
            sub={summary.passed === 1 ? "check" : "checks"}
            value={String(summary.passed)}
            color={SUCCESS}
            bg={SUCCESS_BG}
          />
          <KpiCard
            label="Failed"
            sub={summary.failed === 1 ? "check" : "checks"}
            value={String(summary.failed)}
            color={DESTRUCTIVE}
            bg={DESTRUCTIVE_BG}
          />
          <KpiCard
            label="Warnings"
            sub={summary.warned === 1 ? "check" : "checks"}
            value={String(summary.warned)}
            color={chrome.amberDark}
            bg={chrome.amberBg}
          />
          <KpiCard
            label="Not applicable"
            sub={summary.not_applicable === 1 ? "check" : "checks"}
            value={String(summary.not_applicable)}
            color={chrome.mutedFg}
            bg={chrome.muted}
          />
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
        <button type="button" style={secondaryBtnStyle} onClick={onGoTolerances}>
          Fee tolerances
        </button>
        <button type="button" style={secondaryBtnStyle} onClick={onGoAudit}>
          Audit report
        </button>
        <button type="button" style={ctaBtnStyle} onClick={onGoViolations}>
          View violations ({summary.failed + summary.warned}) →
        </button>
      </div>
    </div>
  );
}

/* ----- Disclosures ---------------------------------------------------- */

// Static disclosure checklist — mirrors the demo. When the real pipeline
// lands this reads from ecv_documents + derived disclosure metadata; for
// now it's the same canned list so the reviewer sees the same rows.
const DISCLOSURES = [
  { name: "Loan Estimate (LE)", regulation: "TRID / Reg Z", status: "present", delivered: "Feb 16, 2026", signed: true },
  { name: "Closing Disclosure (CD)", regulation: "TRID / Reg Z", status: "present", delivered: "Mar 25, 2026", signed: true },
  { name: "Affiliated Business Arrangement", regulation: "RESPA Section 8", status: "present", delivered: "Feb 16, 2026", signed: true },
  { name: "Lead Paint Disclosure", regulation: "42 USC 4852d", status: "present", delivered: "Feb 20, 2026", signed: true },
  { name: "Radon Disclosure (Illinois)", regulation: "IL 420 ILCS 46", status: "missing", delivered: null, signed: false },
  { name: "Equal Credit Opportunity Notice", regulation: "ECOA / Reg B", status: "present", delivered: "Feb 14, 2026", signed: true },
  { name: "Initial Escrow Account Statement", regulation: "RESPA Section 10", status: "present", delivered: "Mar 27, 2026", signed: false },
  { name: "HMDA Data Collection Notice", regulation: "HMDA / Reg C", status: "present", delivered: "Feb 14, 2026", signed: true },
] as const;

function DisclosuresTab() {
  return (
    <div style={{ ...cardStyle }}>
      <div
        style={{
          background: chrome.amberBg,
          borderBottom: `1px solid ${chrome.amberLight}`,
          padding: "14px 20px",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, color: chrome.amberDark }}>
          Required disclosures
        </div>
        <div style={{ fontSize: 12, color: chrome.amberDark, opacity: 0.8, marginTop: 2 }}>
          Federal and state-specific disclosure requirements
        </div>
      </div>
      {DISCLOSURES.map((d, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "12px 20px",
            borderBottom: `1px solid ${chrome.bg}`,
            background: d.status === "missing" ? DESTRUCTIVE_BG : "transparent",
          }}
        >
          <span style={{ fontSize: 14, color: d.status === "present" ? SUCCESS : DESTRUCTIVE }}>
            {d.status === "present" ? "✓" : "✕"}
          </span>
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: d.status === "missing" ? DESTRUCTIVE : chrome.charcoal,
              }}
            >
              {d.name}
            </div>
            <div style={{ fontSize: 10, color: chrome.mutedFg, marginTop: 1 }}>{d.regulation}</div>
          </div>
          {d.delivered && (
            <span style={{ fontSize: 11, color: chrome.mutedFg }}>Delivered: {d.delivered}</span>
          )}
          {d.signed && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 600,
                color: SUCCESS,
                background: SUCCESS_BG,
                padding: "2px 6px",
                borderRadius: 3,
              }}
            >
              SIGNED
            </span>
          )}
          {d.status === "missing" && (
            <span
              style={{
                fontSize: 9,
                fontWeight: 700,
                color: DESTRUCTIVE,
                background: DESTRUCTIVE_BG,
                border: `1px solid ${DESTRUCTIVE}33`,
                padding: "2px 6px",
                borderRadius: 3,
              }}
            >
              MISSING
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/* ----- Fee Tolerances ------------------------------------------------- */

function ToleranceTab({ rows }: { rows: FeeTolerance[] }) {
  return (
    <div style={{ ...cardStyle }}>
      <div
        style={{
          background: chrome.amberBg,
          borderBottom: `1px solid ${chrome.amberLight}`,
          padding: "14px 20px",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, color: chrome.amberDark }}>
          Fee tolerance comparison — LE vs CD
        </div>
        <div style={{ fontSize: 12, color: chrome.amberDark, opacity: 0.8, marginTop: 2 }}>
          TRID tolerance buckets per 12 CFR 1026.19(e)(3)
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr 60px",
          gap: 8,
          padding: "8px 20px",
          fontSize: 10,
          color: chrome.mutedFg,
          borderBottom: `1px solid ${chrome.muted}`,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: 0.3,
        }}
      >
        <span>Bucket</span>
        <span style={{ textAlign: "right" }}>LE</span>
        <span style={{ textAlign: "right" }}>CD</span>
        <span style={{ textAlign: "right" }}>Diff</span>
        <span style={{ textAlign: "right" }}>Variance</span>
        <span style={{ textAlign: "center" }}>Status</span>
      </div>
      {rows.map((row) => {
        const st = statusStyle(row.status);
        return (
          <div
            key={row.id}
            style={{
              display: "grid",
              gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr 60px",
              gap: 8,
              padding: "10px 20px",
              borderBottom: `1px solid ${chrome.muted}`,
              fontSize: 12,
              alignItems: "center",
            }}
          >
            <span style={{ fontWeight: 600 }}>{row.bucket}</span>
            <span style={{ color: chrome.mutedFg, textAlign: "right" }}>{row.le}</span>
            <span style={{ color: chrome.mutedFg, textAlign: "right" }}>{row.cd}</span>
            <span style={{ fontWeight: 600, textAlign: "right" }}>{row.diff}</span>
            <span style={{ fontWeight: 600, textAlign: "right", color: st.color }}>
              {row.pct}
            </span>
            <span
              style={{
                fontSize: 9,
                fontWeight: 700,
                color: st.color,
                background: st.bg,
                padding: "2px 6px",
                borderRadius: 3,
                textAlign: "center",
              }}
            >
              {st.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ----- Violations ----------------------------------------------------- */

function ViolationsTab({
  violations,
  expandedId,
  onToggle,
  failed,
  warned,
}: {
  violations: ComplianceCheck[];
  expandedId: string | null;
  onToggle: (id: string) => void;
  failed: number;
  warned: number;
}) {
  if (violations.length === 0) {
    return (
      <div style={{ ...cardStyle, padding: 32, textAlign: "center", color: chrome.mutedFg }}>
        No violations or warnings.
      </div>
    );
  }

  return (
    <div style={{ ...cardStyle }}>
      <div
        style={{
          background: DESTRUCTIVE_BG,
          borderBottom: `1px solid ${DESTRUCTIVE}33`,
          padding: "14px 20px",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, color: "#991B1B" }}>
          Regulatory violations & warnings
        </div>
        <div style={{ fontSize: 12, color: "#991B1B", opacity: 0.7, marginTop: 2 }}>
          {failed} violation{failed !== 1 ? "s" : ""}, {warned} warning
          {warned !== 1 ? "s" : ""} requiring attention
        </div>
      </div>
      {violations.map((c) => {
        const st = statusStyle(c.status);
        const isExp = expandedId === c.id;
        return (
          <div
            key={c.id}
            onClick={() => onToggle(c.id)}
            style={{
              padding: "14px 20px",
              borderBottom: `1px solid ${chrome.muted}`,
              cursor: "pointer",
              background: isExp ? chrome.bg : "transparent",
              borderLeft: `3px solid ${st.color}`,
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
              <span
                style={{
                  fontSize: 11,
                  fontFamily: "monospace",
                  color: chrome.mutedFg,
                  minWidth: 38,
                }}
              >
                {c.check_code}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{c.category}</span>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      color: st.color,
                      background: st.bg,
                      padding: "2px 6px",
                      borderRadius: 3,
                    }}
                  >
                    {st.label}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 2 }}>{c.rule}</div>
                {isExp && (
                  <div style={{ marginTop: 10 }} onClick={(e) => e.stopPropagation()}>
                    <p
                      style={{
                        fontSize: 12,
                        color: chrome.charcoal,
                        lineHeight: 1.6,
                        margin: "0 0 12px",
                      }}
                    >
                      {c.detail}
                    </p>
                    {c.ai_note && <AiNoteCallout note={c.ai_note} />}
                    {c.mismo.length > 0 && <MismoPanel fields={c.mismo} />}
                  </div>
                )}
              </div>
              <span
                style={{
                  fontSize: 10,
                  color: chrome.mutedFg,
                  transform: isExp ? "rotate(180deg)" : "",
                  transition: "transform 0.2s",
                }}
              >
                ▼
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ----- Phase-7 primitives (inline — extracted in a later slice) ------- */

function AiNoteCallout({ note }: { note: string }) {
  return (
    <div
      style={{
        background: chrome.amberBg,
        border: `1px solid ${chrome.amberLight}`,
        borderLeft: `3px solid ${chrome.amberDark}`,
        borderRadius: 6,
        padding: "10px 14px",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: chrome.amberDark,
          letterSpacing: 0.5,
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        Compliance officer&apos;s note
      </div>
      <div style={{ fontSize: 12, color: chrome.charcoal, lineHeight: 1.55 }}>{note}</div>
    </div>
  );
}

function MismoPanel({ fields }: { fields: MismoField[] }) {
  return (
    <div
      style={{
        border: `1px solid ${chrome.border}`,
        borderRadius: 6,
        overflow: "hidden",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          background: chrome.muted,
          padding: "8px 12px",
          fontSize: 10,
          fontWeight: 700,
          color: chrome.mutedFg,
          letterSpacing: 0.5,
          textTransform: "uppercase",
        }}
      >
        MISMO 3.6 extractions
      </div>
      {fields.map((f, i) => (
        <div
          key={i}
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1.5fr 1.5fr 60px",
            gap: 8,
            padding: "8px 12px",
            fontSize: 11,
            borderTop: i === 0 ? "none" : `1px solid ${chrome.bg}`,
            alignItems: "center",
          }}
        >
          <span
            style={{
              fontFamily: "monospace",
              fontSize: 10,
              color: chrome.mutedFg,
            }}
          >
            {f.entity}
          </span>
          <span style={{ fontSize: 11, color: chrome.charcoal }}>{f.field}</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: chrome.charcoal }}>{f.value}</span>
          <span
            style={{
              fontSize: 10,
              color: f.confidence >= 85 ? SUCCESS : f.confidence >= 50 ? chrome.amberDark : DESTRUCTIVE,
              textAlign: "right",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {f.confidence}%
          </span>
        </div>
      ))}
    </div>
  );
}

/* ----- Audit Report --------------------------------------------------- */

function AuditTab({ summary }: { summary: ComplianceSummary }) {
  return (
    <div style={{ maxWidth: 640 }}>
      <div style={{ ...cardStyle }}>
        <div
          style={{
            background: `linear-gradient(135deg, ${chrome.amberBg}, rgba(212,147,15,0.08))`,
            padding: "32px 28px",
            display: "flex",
            alignItems: "center",
            gap: 20,
          }}
        >
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 16,
              background: `${chrome.amberDark}20`,
              border: `1px solid ${chrome.amberDark}30`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 26,
              color: chrome.amberDark,
            }}
          >
            ⚖
          </div>
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 4px" }}>
              Compliance audit report
            </h2>
            <p style={{ fontSize: 12, color: chrome.mutedFg, margin: 0 }}>
              Complete regulatory compliance assessment with findings, violations, and corrective
              actions
            </p>
          </div>
        </div>
        <div style={{ padding: "16px 28px", borderTop: `1px solid ${chrome.border}` }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              gap: 10,
              marginBottom: 16,
            }}
          >
            <AuditStat count={summary.failed} label="Violations" color={DESTRUCTIVE} bg={DESTRUCTIVE_BG} />
            <AuditStat
              count={summary.warned}
              label="Warnings"
              color={chrome.amberDark}
              bg={chrome.amberBg}
            />
            <AuditStat count={summary.passed} label="Passed" color={SUCCESS} bg={SUCCESS_BG} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {[
              "Compliance score and executive summary",
              "TRID disclosure timing verification",
              "Fee tolerance analysis (LE vs CD)",
              "All violations with corrective actions",
              "State-specific disclosure checklist",
              "HMDA data accuracy assessment",
              "AI Compliance Officer recommendations",
            ].map((item) => (
              <div
                key={item}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 12,
                  color: chrome.charcoal,
                }}
              >
                <span style={{ color: SUCCESS }}>✓</span> {item}
              </div>
            ))}
          </div>
        </div>
        <div
          style={{
            padding: "16px 28px",
            borderTop: `1px solid ${chrome.border}`,
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            background: `${chrome.muted}80`,
          }}
        >
          <button type="button" style={ctaBtnStyle}>
            Download PDF
          </button>
          <button type="button" style={purpleBtnStyle}>
            MISMO XML
          </button>
        </div>
      </div>
    </div>
  );
}

function AuditStat({
  count,
  label,
  color,
  bg,
}: {
  count: number;
  label: string;
  color: string;
  bg: string;
}) {
  return (
    <div
      style={{
        background: bg,
        borderRadius: 8,
        padding: "10px 14px",
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      <div style={{ fontSize: 20, fontWeight: 800, color }}>{count}</div>
      <div style={{ fontSize: 11, color }}>{label}</div>
    </div>
  );
}

function KpiCard({
  label,
  sub,
  value,
  color,
  bg,
  large,
}: {
  label: string;
  sub: string;
  value: string;
  color: string;
  bg: string;
  large?: boolean;
}) {
  return (
    <div
      style={{
        background: bg,
        borderRadius: 12,
        padding: large ? "20px 22px" : "14px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        borderLeft: `4px solid ${color}`,
        boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
      }}
    >
      <div>
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            color,
            letterSpacing: 0.6,
            textTransform: "uppercase",
          }}
        >
          {label}
        </div>
        <div style={{ fontSize: 11, color, opacity: 0.7, marginTop: 2 }}>{sub}</div>
      </div>
      <div
        style={{
          fontSize: large ? 38 : 28,
          fontWeight: 800,
          color,
          letterSpacing: "-0.02em",
          lineHeight: 1,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}

/* ----- shared styles -------------------------------------------------- */

const cardStyle: React.CSSProperties = {
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 10,
  boxShadow: "0 1px 2px rgba(20,18,14,0.03)",
  overflow: "hidden",
};

const titleStyle: React.CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  color: chrome.charcoal,
  margin: "0 0 12px",
  fontFamily: typography.fontFamily.primary,
};

const emptyStyle: React.CSSProperties = {
  fontSize: 13,
  color: chrome.mutedFg,
};

const errorBoxStyle: React.CSSProperties = {
  padding: "12px 16px",
  background: DESTRUCTIVE_BG,
  border: `1px solid ${DESTRUCTIVE}33`,
  borderLeft: `4px solid ${DESTRUCTIVE}`,
  borderRadius: 6,
  color: DESTRUCTIVE,
  fontSize: 13,
};

const linkBtnStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "8px 16px",
  background: chrome.amberDark,
  color: "#fff",
  borderRadius: 6,
  textDecoration: "none",
  fontSize: 13,
  fontWeight: 600,
  border: "none",
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const ctaBtnStyle: React.CSSProperties = {
  padding: "10px 16px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: 8,
  border: "none",
  background: chrome.amberDark,
  color: "#fff",
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
  textDecoration: "none",
  display: "inline-block",
};

const secondaryBtnStyle: React.CSSProperties = {
  padding: "10px 16px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: 8,
  border: `1px solid ${chrome.border}`,
  background: chrome.card,
  color: chrome.charcoal,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
  textDecoration: "none",
  display: "inline-block",
};

const purpleBtnStyle: React.CSSProperties = {
  padding: "10px 16px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: 8,
  border: "1px solid #BD33A4",
  background: "#BD33A412",
  color: "#BD33A4",
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

