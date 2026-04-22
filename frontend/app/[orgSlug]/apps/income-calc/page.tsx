"use client";

/**
 * Income Calculation micro-app page (US-6.4).
 *
 * Five tabs matching the one-logikality-demo reference 1:1:
 *  - Overview — summary bullets + KPI cards (qualifies / monthly / annual / DTI)
 *  - Employment — borrower employment verification panel + AI note + MISMO
 *  - Income Sources — expandable per-source rows (base / OT / bonus / rental)
 *  - DTI Analysis — income / debt / DTI cards + itemized debt breakdown
 *  - Worksheet — Fannie Mae Form 1008 export surface
 *
 * Data source: GET /api/packets/{id}/income. The ECV launcher routes
 * here when the org is subscribed+enabled AND income-calc is `ready`.
 * Server re-checks the subscription so a deep link can't bypass gating.
 */

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

/* ----- types ---------------------------------------------------------- */

type Trend = "stable" | "increasing" | "decreasing";

type MismoField = {
  entity: string;
  field: string;
  value: string;
  confidence: number;
};

type IncomeSource = {
  id: string;
  source_code: string;
  source_name: string;
  employer: string | null;
  position: string | null;
  income_type: string;
  monthly: number;
  annual: number;
  trend: Trend;
  years: number;
  confidence: number;
  ai_note: string | null;
  mismo: MismoField[];
  docs: string[];
};

type DtiItem = {
  id: string;
  description: string;
  monthly: number;
};

type IncomeSummary = {
  total_monthly: number;
  total_annual: number;
  total_debt: number;
  dti: number;
  source_count: number;
};

type IncomeDashboard = {
  summary: IncomeSummary;
  sources: IncomeSource[];
  dti_items: DtiItem[];
};

type Tab = "overview" | "employment" | "sources" | "dti" | "worksheet";

/* ----- palette (aligned with the ECV + Compliance pages) -------------- */

const SUCCESS = "#10B981";
const SUCCESS_BG = "#D1FAE5";
const DESTRUCTIVE = "#DC2626";
const DESTRUCTIVE_BG = "#FEE2E2";

const money = (n: number, dp = 2) =>
  n.toLocaleString("en", { minimumFractionDigits: dp, maximumFractionDigits: dp });

/* ----- page ----------------------------------------------------------- */

export default function IncomeCalcPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const searchParams = useSearchParams();
  const packetId = searchParams.get("packet");
  const router = useRouter();
  const { ready } = useRequireRole(["customer_admin", "customer_user"], `/${orgSlug}`);
  const { token } = useAuth();

  const [data, setData] = useState<IncomeDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token || !packetId) return;
    let cancelled = false;
    (async () => {
      try {
        const payload = await api<IncomeDashboard>(
          `/api/packets/${packetId}/income`,
          { token },
        );
        if (!cancelled) setData(payload);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          setError("The Income Calculation app is not enabled for your organization.");
        } else if (err instanceof ApiError && err.status === 409) {
          setError("Income findings are still being computed. Check back shortly.");
        } else if (err instanceof ApiError && err.status === 404) {
          setError("Packet not found.");
        } else {
          setError("Couldn't load income analysis.");
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
        <h1 style={titleStyle}>Income Calculation</h1>
        <p style={emptyStyle}>
          Open a packet from the ECV dashboard to run income analysis.
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
        <h1 style={titleStyle}>Income Calculation</h1>
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
        <h1 style={titleStyle}>Income Calculation</h1>
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
  data: IncomeDashboard;
  orgSlug: string;
  packetId: string;
}) {
  const { summary, sources, dti_items: dtiItems } = data;
  const [tab, setTab] = useState<Tab>("overview");
  const [expandedId, setExpandedId] = useState<string | null>(null);

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
          <h1 style={{ ...titleStyle, margin: "0 0 6px" }}>Income qualification analysis</h1>
          <div style={{ display: "flex", gap: 16, fontSize: 12, color: chrome.mutedFg }}>
            <span>
              Packet:{" "}
              <strong style={{ color: chrome.charcoal, fontFamily: "monospace" }}>
                {packetId.slice(0, 8)}
              </strong>
            </span>
            <span>
              Guidelines: <strong style={{ color: chrome.charcoal }}>Fannie Mae</strong>
            </span>
            <span>
              Sources verified:{" "}
              <strong style={{ color: chrome.charcoal }}>{summary.source_count}</strong>
            </span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href={`/${orgSlug}/ecv?packet=${packetId}`} style={secondaryBtnStyle}>
            Back to ECV
          </Link>
          <button type="button" style={ctaBtnStyle} onClick={() => setTab("worksheet")}>
            Export worksheet
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
            { key: "employment", label: "Employment" },
            { key: "sources", label: "Income Sources" },
            { key: "dti", label: "DTI Analysis" },
            { key: "worksheet", label: "Worksheet" },
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
          onGoDti={() => setTab("dti")}
          onGoSources={() => setTab("sources")}
          onGoWorksheet={() => setTab("worksheet")}
        />
      )}
      {tab === "employment" && <EmploymentTab />}
      {tab === "sources" && (
        <SourcesTab
          sources={sources}
          totalMonthly={summary.total_monthly}
          expandedId={expandedId}
          onToggle={(id) => setExpandedId((prev) => (prev === id ? null : id))}
        />
      )}
      {tab === "dti" && <DtiTab summary={summary} items={dtiItems} />}
      {tab === "worksheet" && <WorksheetTab summary={summary} />}
    </div>
  );
}

/* ----- Overview ------------------------------------------------------- */

function OverviewTab({
  summary,
  onGoDti,
  onGoSources,
  onGoWorksheet,
}: {
  summary: IncomeSummary;
  onGoDti: () => void;
  onGoSources: () => void;
  onGoWorksheet: () => void;
}) {
  const dti = summary.dti;
  const qualifies = dti <= 45;
  const dtiColor = dti <= 43 ? SUCCESS : dti <= 50 ? chrome.amberDark : DESTRUCTIVE;
  const dtiBg = dti <= 43 ? SUCCESS_BG : dti <= 50 ? chrome.amberBg : DESTRUCTIVE_BG;

  const bullets = [
    `Borrower qualifies under Fannie Mae guidelines with a total monthly income of $${money(summary.total_monthly)} from ${summary.source_count} sources.`,
    "Base employment income is the primary source — 6.2 years with Midwest Engineering Corp, well above the 2-year minimum.",
    "Overtime shows an increasing trend over 3 years, supporting full inclusion in qualifying income.",
    "Rental income has lower confidence at 79% — manual verification of lease terms recommended.",
    `DTI ratio of ${dti.toFixed(1)}% is within the 45% Fannie Mae limit, providing a ${(45 - dti).toFixed(1)}% buffer.`,
  ];

  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)",
          gap: 20,
          marginBottom: 20,
          alignItems: "flex-start",
        }}
      >
        {/* LEFT — summary bullets */}
        <div
          style={{
            background: chrome.card,
            borderRadius: 12,
            border: `1px solid ${chrome.border}`,
            boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
            padding: "28px 32px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 18 }}>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: chrome.mutedFg,
                letterSpacing: 1,
                textTransform: "uppercase",
              }}
            >
              Income qualification summary
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

        {/* RIGHT — KPI stack */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <KpiCard
            label="Qualification"
            sub={qualifies ? "Meets Fannie Mae limits" : "Exceeds guidelines"}
            value={qualifies ? "QUALIFIES" : "EXCEEDS"}
            color={qualifies ? SUCCESS : DESTRUCTIVE}
            bg={qualifies ? SUCCESS_BG : DESTRUCTIVE_BG}
            large
          />
          <KpiCard
            label="Monthly income"
            sub={`${summary.source_count} sources verified`}
            value={`$${summary.total_monthly.toLocaleString("en", { maximumFractionDigits: 0 })}`}
            color={SUCCESS}
            bg={SUCCESS_BG}
          />
          <KpiCard
            label="Annual income"
            sub="Total qualifying"
            value={`$${summary.total_annual.toLocaleString("en", { maximumFractionDigits: 0 })}`}
            color={chrome.charcoal}
            bg={chrome.card}
          />
          <KpiCard
            label="DTI ratio"
            sub="Fannie Mae limit: 45%"
            value={`${dti.toFixed(1)}%`}
            color={dtiColor}
            bg={dtiBg}
          />
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
        <button type="button" onClick={onGoDti} style={secondaryBtnStyle}>
          DTI analysis
        </button>
        <button type="button" onClick={onGoWorksheet} style={secondaryBtnStyle}>
          Worksheet
        </button>
        <button type="button" onClick={onGoSources} style={ctaBtnStyle}>
          View income sources →
        </button>
      </div>
    </div>
  );
}

/* ----- Employment ----------------------------------------------------- */

function EmploymentTab() {
  const fields = [
    { l: "Employer", v: "Midwest Engineering Corp" },
    { l: "Position", v: "Senior Project Manager" },
    { l: "Employment start", v: "January 2020 (6.2 years)" },
    { l: "Employment type", v: "Full-time, W-2 employee" },
    { l: "VOE status", v: "Verified — received Mar 10, 2026" },
    { l: "Stability assessment", v: "Stable — no gaps, consistent tenure" },
  ];
  const mismo: MismoField[] = [
    { entity: "EMPLOYMENT", field: "EmployerName", value: "Midwest Engineering Corp", confidence: 97 },
    { entity: "EMPLOYMENT", field: "PositionTitle", value: "Senior Project Manager", confidence: 94 },
    { entity: "EMPLOYMENT", field: "StartDate", value: "2020-01-06", confidence: 92 },
    { entity: "EMPLOYMENT", field: "EmploymentType", value: "FULL_TIME", confidence: 98 },
    { entity: "EMPLOYMENT", field: "VOEVerified", value: "true", confidence: 96 },
  ];

  return (
    <div style={cardStyle}>
      <div
        style={{
          background: chrome.amberBg,
          borderBottom: `1px solid ${chrome.amberLight}`,
          padding: "14px 20px",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, color: chrome.amberDark }}>
          Employment verification
        </div>
        <div style={{ fontSize: 12, color: chrome.amberDark, marginTop: 2 }}>
          Per Fannie Mae Selling Guide, Section B3-3.1
        </div>
      </div>
      <div style={{ padding: 20 }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 16,
            marginBottom: 20,
          }}
        >
          {fields.map((f) => (
            <div key={f.l}>
              <div
                style={{
                  fontSize: 10,
                  color: chrome.mutedFg,
                  marginBottom: 2,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                {f.l}
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: chrome.charcoal }}>{f.v}</div>
            </div>
          ))}
        </div>

        <AiNoteCallout
          label="Underwriter's note"
          note="Employment verified through VOE received March 10, 2026. Borrower has been continuously employed at Midwest Engineering Corp since January 2020 (6.2 years). Position title on VOE matches W-2 and paystub. No probationary period, no planned changes to employment. Meets Fannie Mae 2-year employment history requirement with significant margin."
        />

        <MismoPanel fields={mismo} />
      </div>
    </div>
  );
}

/* ----- Income Sources ------------------------------------------------- */

function SourcesTab({
  sources,
  totalMonthly,
  expandedId,
  onToggle,
}: {
  sources: IncomeSource[];
  totalMonthly: number;
  expandedId: string | null;
  onToggle: (id: string) => void;
}) {
  return (
    <div style={{ ...cardStyle, marginBottom: 12 }}>
      <div
        style={{
          background: chrome.amberBg,
          borderBottom: `1px solid ${chrome.amberLight}`,
          padding: "14px 20px",
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 700, color: chrome.amberDark }}>
          Income by source
        </div>
        <div style={{ fontSize: 12, color: chrome.amberDark, marginTop: 2 }}>
          Per Fannie Mae Selling Guide, Section B3-3
        </div>
      </div>

      {sources.map((inc) => {
        const isExp = expandedId === inc.id;
        const trendColor = inc.trend === "increasing" ? SUCCESS : chrome.mutedFg;
        const trendBg = inc.trend === "increasing" ? SUCCESS_BG : chrome.muted;
        return (
          <div
            key={inc.id}
            onClick={() => onToggle(inc.id)}
            style={{
              padding: "14px 20px",
              borderBottom: `1px solid ${chrome.muted}`,
              cursor: "pointer",
              background: isExp ? chrome.bg : "transparent",
              transition: "background 0.15s",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span
                style={{
                  fontSize: 11,
                  fontFamily: "monospace",
                  color: chrome.mutedFg,
                  minWidth: 32,
                }}
              >
                {inc.source_code}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: chrome.charcoal }}>
                    {inc.source_name}
                  </span>
                  <span
                    style={{
                      fontSize: 9,
                      color: chrome.mutedFg,
                      background: chrome.muted,
                      padding: "2px 6px",
                      borderRadius: 3,
                    }}
                  >
                    {inc.income_type}
                  </span>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 600,
                      color: trendColor,
                      background: trendBg,
                      padding: "2px 6px",
                      borderRadius: 3,
                      textTransform: "uppercase",
                    }}
                  >
                    {inc.trend}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 2 }}>
                  {inc.employer ?? inc.position ?? "—"} · {inc.years}yr history · ECV confidence:{" "}
                  {inc.confidence}%
                </div>
              </div>
              <div style={{ textAlign: "right", minWidth: 100 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: chrome.charcoal }}>
                  ${money(inc.monthly)}
                </div>
                <div style={{ fontSize: 10, color: chrome.mutedFg }}>/month</div>
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

            {isExp && (
              <div style={{ marginTop: 10 }} onClick={(e) => e.stopPropagation()}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr 1fr",
                    gap: 8,
                    marginBottom: 12,
                  }}
                >
                  <StatCell label="Annual" value={`$${money(inc.annual, 0)}`} />
                  <StatCell label="History" value={`${inc.years} years`} />
                  <StatCell
                    label="Source docs"
                    value={inc.docs.join(", ") || "—"}
                    compact
                  />
                </div>

                {inc.ai_note && <AiNoteCallout label="Underwriter's note" note={inc.ai_note} />}
                <MismoPanel fields={inc.mismo} />
              </div>
            )}
          </div>
        );
      })}

      {/* Total row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "12px 20px",
          background: chrome.amberBg,
        }}
      >
        <span style={{ flex: 1, fontSize: 14, fontWeight: 700, color: chrome.amberDark }}>
          Total qualifying income
        </span>
        <span
          style={{
            fontSize: 16,
            fontWeight: 800,
            color: chrome.amberDark,
            marginRight: 26,
          }}
        >
          ${money(totalMonthly)} /month
        </span>
      </div>
    </div>
  );
}

function StatCell({
  label,
  value,
  compact,
}: {
  label: string;
  value: string;
  compact?: boolean;
}) {
  return (
    <div style={{ padding: "8px 10px", borderRadius: 6, background: chrome.muted }}>
      <div style={{ fontSize: 9, color: chrome.mutedFg }}>{label}</div>
      <div
        style={{
          fontSize: compact ? 11 : 13,
          fontWeight: compact ? 600 : 700,
          color: chrome.charcoal,
        }}
      >
        {value}
      </div>
    </div>
  );
}

/* ----- DTI Analysis --------------------------------------------------- */

function DtiTab({ summary, items }: { summary: IncomeSummary; items: DtiItem[] }) {
  const dti = summary.dti;
  const dtiColor = dti <= 45 ? SUCCESS : DESTRUCTIVE;
  const dtiBg = dti <= 45 ? SUCCESS_BG : DESTRUCTIVE_BG;
  const buffer = (45 - dti).toFixed(1);

  return (
    <div>
      {/* Summary cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 10,
          marginBottom: 16,
        }}
      >
        <DtiCard
          label="Total monthly income"
          value={`$${money(summary.total_monthly)}`}
          color={SUCCESS}
        />
        <DtiCard
          label="Total monthly debt"
          value={`$${money(summary.total_debt)}`}
          color={DESTRUCTIVE}
        />
        <div
          style={{
            background: dtiBg,
            borderRadius: 8,
            padding: 16,
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 10, color: dtiColor, marginBottom: 4 }}>DTI ratio</div>
          <div style={{ fontSize: 28, fontWeight: 800, color: dtiColor }}>{dti.toFixed(1)}%</div>
          <div style={{ fontSize: 9, color: chrome.mutedFg, marginTop: 2 }}>
            Limit: 45% · Buffer: {buffer}%
          </div>
        </div>
      </div>

      {/* Breakdown */}
      <div style={{ ...cardStyle, marginBottom: 16 }}>
        <div
          style={{
            background: chrome.amberBg,
            borderBottom: `1px solid ${chrome.amberLight}`,
            padding: "14px 20px",
          }}
        >
          <div style={{ fontSize: 15, fontWeight: 700, color: chrome.amberDark }}>
            Debt-to-income breakdown
          </div>
          <div style={{ fontSize: 12, color: chrome.amberDark, marginTop: 2 }}>
            Per Fannie Mae Selling Guide, Section B3-6
          </div>
        </div>
        <div
          style={{
            padding: "8px 20px",
            borderBottom: `1px solid ${chrome.muted}`,
            fontSize: 10,
            fontWeight: 600,
            color: chrome.mutedFg,
            textTransform: "uppercase",
            letterSpacing: 0.3,
          }}
        >
          Monthly obligations
        </div>
        {items.map((row) => (
          <div
            key={row.id}
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "10px 20px",
              borderBottom: `1px solid ${chrome.muted}`,
              fontSize: 12,
              color: chrome.charcoal,
            }}
          >
            <span>{row.description}</span>
            <span style={{ fontWeight: 600 }}>${money(row.monthly)}</span>
          </div>
        ))}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            padding: "12px 20px",
            background: chrome.muted,
            fontSize: 13,
            fontWeight: 700,
            color: chrome.charcoal,
          }}
        >
          <span>Total monthly obligations</span>
          <span>${money(summary.total_debt)}</span>
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            padding: "12px 20px",
            fontSize: 13,
            borderTop: `1px solid ${chrome.border}`,
            color: chrome.charcoal,
          }}
        >
          <span style={{ fontWeight: 700 }}>DTI ratio</span>
          <span style={{ fontWeight: 800, color: dtiColor }}>
            {dti.toFixed(1)}%{" "}
            <span style={{ fontWeight: 400, fontSize: 11, color: chrome.mutedFg }}>
              / 45% limit
            </span>
          </span>
        </div>
      </div>

      <AiNoteCallout
        label="Underwriter's note"
        note={`Borrower's DTI of ${dti.toFixed(
          1,
        )}% is within the Fannie Mae 45% guideline limit, providing a ${buffer}% buffer. Housing expense ratio (front-end DTI) is within the typical 28% soft limit. The auto loan ($380/mo) has 24 months remaining and the student loan ($250/mo) is on a standard 10-year repayment plan. No other recurring obligations were identified. Income stability is strong across all ${summary.source_count} sources.`}
      />
    </div>
  );
}

function DtiCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div
      style={{
        background: chrome.card,
        borderRadius: 8,
        padding: 16,
        textAlign: "center",
        border: `1px solid ${chrome.border}`,
      }}
    >
      <div style={{ fontSize: 10, color: chrome.mutedFg, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, color }}>{value}</div>
    </div>
  );
}

/* ----- Worksheet ------------------------------------------------------ */

function WorksheetTab({ summary }: { summary: IncomeSummary }) {
  const qualifies = summary.dti <= 45;
  return (
    <div style={{ maxWidth: 640 }}>
      <div style={{ ...cardStyle, borderRadius: 12 }}>
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
              fontWeight: 700,
            }}
          >
            $
          </div>
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 4px", color: chrome.charcoal }}>
              Income calculation worksheet
            </h2>
            <p style={{ fontSize: 12, color: chrome.mutedFg, margin: 0 }}>
              Fannie Mae Form 1008 — income analysis and DTI qualification worksheet
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
            <WorksheetStat
              value={`$${summary.total_monthly.toLocaleString("en", { maximumFractionDigits: 0 })}`}
              label="Monthly income"
              color={SUCCESS}
              bg={SUCCESS_BG}
            />
            <WorksheetStat
              value={`${summary.dti.toFixed(1)}%`}
              label="DTI ratio"
              color={chrome.amberDark}
              bg={chrome.amberBg}
            />
            <WorksheetStat
              value={qualifies ? "QUALIFIES" : "EXCEEDS"}
              label="Decision"
              color={qualifies ? SUCCESS : DESTRUCTIVE}
              bg={qualifies ? SUCCESS_BG : DESTRUCTIVE_BG}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {[
              "Borrower income summary (all sources)",
              "Employment verification details",
              "Income trending analysis (2-year)",
              "DTI calculation with housing ratio",
              "Fannie Mae guideline compliance",
              "AI Underwriter recommendations",
              "MISMO 3.6 income field mapping",
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

function WorksheetStat({
  value,
  label,
  color,
  bg,
}: {
  value: string;
  label: string;
  color: string;
  bg: string;
}) {
  return (
    <div style={{ background: bg, borderRadius: 8, padding: "10px 14px" }}>
      <div style={{ fontSize: 20, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 10, color }}>{label}</div>
    </div>
  );
}

/* ----- shared AI + MISMO primitives (Phase 7) ------------------------- */

function AiNoteCallout({ label, note }: { label: string; note: string }) {
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
        {label}
      </div>
      <div style={{ fontSize: 12, color: chrome.charcoal, lineHeight: 1.55 }}>{note}</div>
    </div>
  );
}

function MismoPanel({ fields }: { fields: MismoField[] }) {
  if (fields.length === 0) return null;
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
          <span style={{ fontFamily: "monospace", fontSize: 10, color: chrome.mutedFg }}>
            {f.entity}
          </span>
          <span style={{ fontSize: 11, color: chrome.charcoal }}>{f.field}</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: chrome.charcoal }}>{f.value}</span>
          <span
            style={{
              fontSize: 10,
              color:
                f.confidence >= 85
                  ? SUCCESS
                  : f.confidence >= 50
                    ? chrome.amberDark
                    : DESTRUCTIVE,
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
        border: bg === chrome.card ? `1px solid ${chrome.border}` : undefined,
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
          fontSize: large ? 22 : 24,
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
