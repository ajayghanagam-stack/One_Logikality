"use client";

/**
 * Title Examination micro-app page (US-6.2).
 *
 * Four tabs matching the one-logikality-demo reference:
 *  - Overview — bullet summary, severity KPI cards, and the four
 *    collapsible schedules (B, C, warnings, curative checklist).
 *  - View Results — Schedule B specific exceptions drilled down with
 *    Phase 7 primitives (AI note, MISMO panel, evidence citations).
 *  - View Pages — placeholder for source-document OCR overlay.
 *  - Export Report — PDF + MISMO 3.6 XML surface.
 *
 * The curative checklist PATCHes `/api/packets/{id}/title-exam/checklist/{item_id}`
 * on toggle and updates progress optimistically; a reload reflects the
 * server-truth state.
 */

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

/* ----- types ---------------------------------------------------------- */

type Severity = "critical" | "high" | "medium" | "low";
type Schedule = "standard" | "specific";

// TI Hub-parity types — every field mirrors
// title_intelligence_hub's ExaminerFlag / FlagResponse shape.
type FlagKind = "exception" | "warning";
type FlagStatus = "open" | "reviewed" | "closed";
type ReviewDecision = "approve" | "reject" | "escalate";

type EvidenceRef = {
  page_number?: number;
  text_snippet?: string;
  [k: string]: unknown;
};

type ReviewOut = {
  id: string;
  flag_id: string;
  flag_kind: FlagKind;
  reviewer_id: string;
  decision: ReviewDecision;
  reason_code: string;
  notes: string | null;
  created_at: string;
};

type ExceptionOut = {
  id: string;
  schedule: Schedule;
  number: number;
  severity: Severity;
  title: string;
  description: string;
  page_ref: string | null;
  note: string | null;
  // TI Hub superset fields.
  flag_type: string | null;
  ai_explanation: string | null;
  evidence_refs: EvidenceRef[];
  status: FlagStatus;
  reviews: ReviewOut[];
};

type RequirementOut = {
  id: string;
  number: number;
  title: string;
  priority: "must_close" | "should_close" | "recommended";
  status: "open" | "requested" | "provided" | "not_ordered";
  page_ref: string | null;
  description: string;
  note: string | null;
  ai_explanation: string | null;
  evidence_refs: EvidenceRef[];
};

type WarningOut = {
  id: string;
  severity: Severity;
  title: string;
  description: string;
  note: string | null;
  flag_type: string | null;
  ai_explanation: string | null;
  evidence_refs: EvidenceRef[];
  status: FlagStatus;
  reviews: ReviewOut[];
};

type RecommendationResponse = {
  decision: ReviewDecision;
  reasoning: string;
  confidence: number;
};

type ChecklistItemOut = {
  id: string;
  number: number;
  action: string;
  priority: string;
  checked: boolean;
  note: string | null;
};

type SeverityCounts = {
  critical: number;
  high: number;
  medium: number;
  low: number;
  total: number;
};

type ChecklistProgress = { completed: number; total: number };

type TitleExamDashboard = {
  severity_counts: SeverityCounts;
  standard_exceptions: ExceptionOut[];
  specific_exceptions: ExceptionOut[];
  requirements: RequirementOut[];
  warnings: WarningOut[];
  checklist: ChecklistItemOut[];
  checklist_progress: ChecklistProgress;
};

type Tab = "overview" | "results" | "pages" | "export";

/* ----- palette -------------------------------------------------------- */

const DESTRUCTIVE = "#DC2626";
const DESTRUCTIVE_BG = "#FEE2E2";

const SEV_COLORS: Record<Severity, { bg: string; text: string; badge: string }> = {
  critical: { bg: "#FEE2E2", text: "#991B1B", badge: "#DC2626" },
  high: { bg: "#FEF3C7", text: "#78350F", badge: "#D97706" },
  medium: { bg: "#FEF9C3", text: "#713F12", badge: "#CA8A04" },
  low: { bg: "#DBEAFE", text: "#1E3A8A", badge: "#2563EB" },
};

const SEV_DISPLAY: Record<Severity, string> = {
  critical: "CRITICAL",
  high: "HIGH",
  medium: "MODERATE",
  low: "STANDARD",
};

const SEV_NAMES: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

const PRIORITY_COLORS: Record<string, { bg: string; text: string }> = {
  must_close: { bg: "#DC2626", text: "#fff" },
  should_close: { bg: "#D97706", text: "#fff" },
  recommended: { bg: "#2563EB", text: "#fff" },
  critical: { bg: "#DC2626", text: "#fff" },
  high: { bg: "#D97706", text: "#fff" },
  medium: { bg: "#CA8A04", text: "#fff" },
};

const PRIORITY_LABEL: Record<string, string> = {
  must_close: "MUST CLOSE",
  should_close: "SHOULD CLOSE",
  recommended: "RECOMMENDED",
};

const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  requested: "Requested",
  provided: "Provided",
  not_ordered: "Not ordered",
};

/* ----- page ----------------------------------------------------------- */

export default function TitleExamPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const searchParams = useSearchParams();
  const packetId = searchParams.get("packet");
  const router = useRouter();
  const { ready } = useRequireRole(["customer_admin", "customer_user"], `/${orgSlug}`);
  const { token } = useAuth();

  const [data, setData] = useState<TitleExamDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token || !packetId) return;
    let cancelled = false;
    (async () => {
      try {
        const payload = await api<TitleExamDashboard>(
          `/api/packets/${packetId}/title-exam`,
          { token },
        );
        if (!cancelled) setData(payload);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          setError("The Title Examination app is not enabled for your organization.");
        } else if (err instanceof ApiError && err.status === 409) {
          setError("Title examination findings are still being computed. Check back shortly.");
        } else if (err instanceof ApiError && err.status === 404) {
          setError("Packet not found.");
        } else {
          setError("Couldn't load title examination.");
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
        <h1 style={titleStyle}>Title Examination</h1>
        <p style={emptyStyle}>Open a packet from the ECV dashboard to run title examination.</p>
        <Link href={`/${orgSlug}/upload`} style={linkBtnStyle}>
          Upload a packet
        </Link>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: 800 }}>
        <h1 style={titleStyle}>Title Examination</h1>
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
        <h1 style={titleStyle}>Title Examination</h1>
        <p style={emptyStyle}>Loading…</p>
      </div>
    );
  }

  return (
    <Dashboard
      data={data}
      setData={setData}
      orgSlug={orgSlug}
      packetId={packetId}
      token={token}
    />
  );
}

/* ----- dashboard ------------------------------------------------------ */

function Dashboard({
  data,
  setData,
  orgSlug,
  packetId,
  token,
}: {
  data: TitleExamDashboard;
  setData: (d: TitleExamDashboard) => void;
  orgSlug: string;
  packetId: string;
  token: string | null;
}) {
  const [tab, setTab] = useState<Tab>("overview");

  const onChecklistToggle = useCallback(
    async (itemId: string, next: boolean) => {
      // Optimistic update.
      const prev = data;
      const optimistic: TitleExamDashboard = {
        ...data,
        checklist: data.checklist.map((c) =>
          c.id === itemId ? { ...c, checked: next } : c,
        ),
        checklist_progress: {
          ...data.checklist_progress,
          completed:
            data.checklist_progress.completed + (next ? 1 : -1),
        },
      };
      setData(optimistic);
      try {
        await api<ChecklistItemOut>(
          `/api/packets/${packetId}/title-exam/checklist/${itemId}`,
          { method: "PATCH", json: { checked: next }, token },
        );
      } catch {
        // Roll back on failure.
        setData(prev);
      }
    },
    [data, packetId, setData, token],
  );

  // POSTs a reviewer decision on a flag, then refetches the dashboard so
  // the flag's status, reviews array, and the overall recommendation all
  // reflect server truth. Matches TI Hub's POST /flags/{id}/reviews.
  const onReviewFlag = useCallback<ReviewHandler>(
    async (kind, flagId, decision) => {
      try {
        await api<ReviewOut>(
          `/api/packets/${packetId}/title-exam/flags/${kind}/${flagId}/reviews`,
          { method: "POST", json: { decision }, token },
        );
        const fresh = await api<TitleExamDashboard>(
          `/api/packets/${packetId}/title-exam`,
          { token },
        );
        setData(fresh);
      } catch {
        // Silent failure — the UI keeps the pre-click state.
      }
    },
    [packetId, setData, token],
  );

  return (
    <div style={{ maxWidth: 1200 }}>
      {/* Breadcrumb */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 12,
          fontSize: 12,
          color: chrome.mutedFg,
        }}
      >
        <Link
          href={`/${orgSlug}/ecv?packet=${packetId}`}
          style={{ color: chrome.mutedFg, textDecoration: "none" }}
        >
          ECV dashboard
        </Link>
        <span>›</span>
        <span style={{ color: chrome.charcoal, fontWeight: 500 }}>
          Title Examination
        </span>
      </div>

      <h1 style={titleStyle}>Title Examination</h1>

      {/* Tabs */}
      <div
        style={{
          display: "flex",
          gap: 4,
          borderBottom: `1px solid ${chrome.border}`,
          marginBottom: 24,
        }}
      >
        {(
          [
            { key: "overview", label: "Overview" },
            { key: "results", label: "View Results" },
            { key: "pages", label: "View Pages" },
            { key: "export", label: "Export Report" },
          ] as const
        ).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: "10px 16px",
              fontSize: 13,
              fontWeight: 500,
              border: "none",
              background: "none",
              cursor: "pointer",
              color: tab === t.key ? chrome.amberDark : chrome.mutedFg,
              borderBottom:
                tab === t.key
                  ? `2px solid ${chrome.amber}`
                  : "2px solid transparent",
              marginBottom: -1,
              fontFamily: typography.fontFamily.primary,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <OverviewTab
          data={data}
          onChecklistToggle={onChecklistToggle}
          onReviewFlag={onReviewFlag}
          packetId={packetId}
          token={token}
          setTab={setTab}
        />
      )}
      {tab === "results" && (
        <ResultsTab data={data} onReviewFlag={onReviewFlag} />
      )}
      {tab === "pages" && <PagesTab />}
      {tab === "export" && <ExportTab data={data} />}
    </div>
  );
}

/* ----- Overview tab --------------------------------------------------- */

function OverviewTab({
  data,
  onChecklistToggle,
  onReviewFlag,
  packetId,
  token,
  setTab,
}: {
  data: TitleExamDashboard;
  onChecklistToggle: (id: string, next: boolean) => void;
  onReviewFlag: ReviewHandler;
  packetId: string;
  token: string | null;
  setTab: (t: Tab) => void;
}) {
  const counts = data.severity_counts;
  const progress = data.checklist_progress;
  const pct =
    progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 0;

  const bullets = [
    `Title examination identified ${data.standard_exceptions.length + data.specific_exceptions.length} exceptions classified under ALTA standards (${data.standard_exceptions.length} standard, ${data.specific_exceptions.length} specific).`,
    `${counts.critical} critical defect${counts.critical === 1 ? "" : "s"} blocking closing — review Schedule B specific exceptions.`,
    `Schedule C lists ${data.requirements.length} requirement${data.requirements.length === 1 ? "" : "s"} that must be satisfied before policy issuance.`,
    `${data.warnings.length} examiner warning${data.warnings.length === 1 ? "" : "s"} flagged during review.`,
    `Curative checklist: ${progress.completed} of ${progress.total} item${progress.total === 1 ? "" : "s"} complete (${pct}%).`,
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
        {/* Summary card */}
        <div style={cardStyle}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 18,
            }}
          >
            <span style={{ fontSize: 16, color: chrome.amber }}>✦</span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: chrome.mutedFg,
                letterSpacing: 1,
                textTransform: "uppercase",
              }}
            >
              Title examination summary
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
                    background: chrome.amber,
                    marginTop: 8,
                    flexShrink: 0,
                  }}
                />
                <span>{point}</span>
              </div>
            ))}
          </div>
        </div>

        {/* KPI cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {(["critical", "high", "medium", "low"] as const).map((sev) => {
            const s = SEV_COLORS[sev];
            return (
              <div
                key={sev}
                style={{
                  background: s.bg,
                  borderRadius: 12,
                  padding: "18px 22px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  borderLeft: `4px solid ${s.badge}`,
                  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
                }}
              >
                <div>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: s.text,
                      letterSpacing: 0.6,
                      textTransform: "uppercase",
                    }}
                  >
                    {SEV_NAMES[sev]}
                  </div>
                  <div
                    style={{ fontSize: 11, color: s.text, opacity: 0.7, marginTop: 2 }}
                  >
                    {counts[sev]} {counts[sev] === 1 ? "item" : "items"}
                  </div>
                </div>
                <div
                  style={{
                    fontSize: 34,
                    fontWeight: 800,
                    color: s.text,
                    letterSpacing: "-0.02em",
                    lineHeight: 1,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {counts[sev]}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <RecommendationBanner packetId={packetId} token={token} />

      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 20 }}>
        <ScheduleBSection
          standard={data.standard_exceptions}
          specific={data.specific_exceptions}
          onReview={onReviewFlag}
        />
        <ScheduleCSection requirements={data.requirements} />
        <WarningsSection warnings={data.warnings} onReview={onReviewFlag} />
        <ChecklistSection
          items={data.checklist}
          progress={progress}
          onToggle={onChecklistToggle}
        />
      </div>

      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
        <button
          type="button"
          onClick={() => setTab("results")}
          style={secondaryBtnStyle}
        >
          View specific exceptions
        </button>
        <button
          type="button"
          onClick={() => setTab("export")}
          style={ctaBtnStyle}
        >
          Export report →
        </button>
      </div>
    </div>
  );
}

/* ----- Schedule section primitives ------------------------------------ */

function Chevron({ collapsed, size = 16 }: { collapsed: boolean; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={chrome.amberDark}
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        transform: collapsed ? "rotate(-90deg)" : "rotate(0)",
        transition: "transform 0.2s",
        flexShrink: 0,
      }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

function SectionHeader({
  title,
  subtitle,
  count,
  collapsed,
  onToggle,
  right,
}: {
  title: string;
  subtitle?: string;
  count?: number;
  collapsed: boolean;
  onToggle: () => void;
  right?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      style={{
        width: "100%",
        background: chrome.amberBg,
        borderBottom: `1px solid ${chrome.amberLight}`,
        padding: "12px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        cursor: "pointer",
        textAlign: "left",
        border: "none",
        fontFamily: typography.fontFamily.primary,
      }}
    >
      <div>
        <h2
          style={{
            fontSize: 15,
            fontWeight: 700,
            margin: 0,
            color: "#78350F",
            letterSpacing: "-0.01em",
          }}
        >
          {title}
          {count !== undefined && (
            <span
              style={{
                marginLeft: 8,
                fontSize: 13,
                fontWeight: 400,
                color: "#B45309B0",
              }}
            >
              ({count})
            </span>
          )}
        </h2>
        {subtitle && (
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#B45309B0" }}>
            {subtitle}
          </p>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {right}
        <Chevron collapsed={collapsed} />
      </div>
    </button>
  );
}

function SubsectionHeader({
  title,
  subtitle,
  count,
  collapsed,
  onToggle,
}: {
  title: string;
  subtitle?: string;
  count?: number;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      style={{
        width: "100%",
        padding: "10px 20px",
        background: "#FAFAF8",
        borderBottom: `1px solid ${chrome.border}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        cursor: "pointer",
        textAlign: "left",
        border: "none",
        fontFamily: typography.fontFamily.primary,
      }}
    >
      <div>
        <h3
          style={{
            fontSize: 12,
            fontWeight: 600,
            margin: 0,
            color: "#57534E",
          }}
        >
          {title}
          {count !== undefined && (
            <span
              style={{
                marginLeft: 6,
                fontSize: 11,
                fontWeight: 400,
                color: "#78716C",
              }}
            >
              ({count})
            </span>
          )}
        </h3>
        {subtitle && (
          <p style={{ margin: "2px 0 0", fontSize: 11, color: "#78716C" }}>
            {subtitle}
          </p>
        )}
      </div>
      <Chevron collapsed={collapsed} size={14} />
    </button>
  );
}

function SevBadge({ severity }: { severity: Severity }) {
  const s = SEV_COLORS[severity];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 3,
        padding: "1px 7px",
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: 0.5,
        background: s.badge,
        color: "#fff",
      }}
    >
      {SEV_DISPLAY[severity]}
    </span>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const key = priority.toLowerCase();
  const p = PRIORITY_COLORS[key] || { bg: "#6B7280", text: "#fff" };
  const label = PRIORITY_LABEL[key] ?? priority.toUpperCase();
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 3,
        padding: "1px 7px",
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: 0.5,
        background: p.bg,
        color: p.text,
      }}
    >
      {label}
    </span>
  );
}

function ExceptionRow({
  item,
  onReview,
}: {
  item: ExceptionOut;
  onReview?: ReviewHandler;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 12,
        padding: "12px 20px",
        borderBottom: `1px solid ${chrome.border}`,
      }}
    >
      <span
        style={{
          fontSize: 12,
          fontFamily: "monospace",
          color: chrome.mutedFg,
          minWidth: 28,
          textAlign: "right",
          paddingTop: 1,
        }}
      >
        {item.number}.
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: chrome.charcoal }}>
            {item.title}
          </span>
          <SevBadge severity={item.severity} />
          {item.flag_type && <FlagTypeBadge flagType={item.flag_type} />}
          <FlagStatusBadge status={item.status} />
          {item.page_ref && (
            <span
              style={{
                fontSize: 10,
                color: chrome.mutedFg,
                fontFamily: "monospace",
              }}
            >
              {item.page_ref}
            </span>
          )}
        </div>
        <p
          style={{
            margin: "4px 0 0",
            fontSize: 12,
            color: chrome.mutedFg,
            lineHeight: 1.55,
          }}
        >
          {item.description}
        </p>
        {item.note && (
          <p
            style={{
              margin: "6px 0 0",
              fontSize: 11,
              color: "#78716C",
              fontStyle: "italic",
              lineHeight: 1.55,
            }}
          >
            <span
              style={{
                fontWeight: 600,
                fontStyle: "normal",
                color: chrome.mutedFg,
              }}
            >
              Note:
            </span>{" "}
            {item.note}
          </p>
        )}
        <FlagMeta
          kind="exception"
          id={item.id}
          aiExplanation={item.ai_explanation}
          evidenceRefs={item.evidence_refs}
          status={item.status}
          reviews={item.reviews}
          onReview={onReview}
        />
      </div>
    </div>
  );
}

/* ----- TI Hub-parity flag metadata ----------------------------------- */

// Reviewer action — matches backend POST /flags/{kind}/{id}/reviews.
type ReviewHandler = (
  kind: FlagKind,
  id: string,
  decision: ReviewDecision,
) => Promise<void> | void;

// Human-readable labels for the 17-value TI Hub flag taxonomy. Kept close
// to the TI Hub wording so output is directly comparable.
const FLAG_TYPE_LABELS: Record<string, string> = {
  missing_endorsement: "Missing endorsement",
  unacceptable_exception: "Unacceptable exception",
  unresolved_lien: "Unresolved lien",
  unreleased_mortgage: "Unreleased mortgage",
  cross_section_mismatch: "Cross-section mismatch",
  requirement_missing_proof: "Requirement missing proof",
  name_discrepancy: "Name discrepancy",
  marital_status_issue: "Marital status issue",
  incomplete_document: "Incomplete document",
  regulatory_compliance: "Regulatory compliance",
  chain_of_title_gap: "Chain of title gap",
  document_defect: "Document defect",
  mineral_rights: "Mineral rights",
  trust_issue: "Trust issue",
  estate_issue: "Estate issue",
  vesting_issue: "Vesting issue",
  tax_issue: "Tax issue",
};

const STATUS_COLORS: Record<FlagStatus, { bg: string; fg: string }> = {
  open: { bg: "#FEF3C7", fg: "#78350F" },
  reviewed: { bg: "#DBEAFE", fg: "#1E40AF" },
  closed: { bg: "#DCFCE7", fg: "#166534" },
};

function FlagTypeBadge({ flagType }: { flagType: string }) {
  const label = FLAG_TYPE_LABELS[flagType] ?? flagType;
  return (
    <span
      style={{
        fontSize: 10,
        padding: "2px 8px",
        borderRadius: 999,
        background: "#EDE9FE",
        color: "#5B21B6",
        fontWeight: 600,
        letterSpacing: 0.2,
      }}
      title={flagType}
    >
      {label}
    </span>
  );
}

function FlagStatusBadge({ status }: { status: FlagStatus }) {
  const c = STATUS_COLORS[status];
  return (
    <span
      style={{
        fontSize: 10,
        padding: "2px 8px",
        borderRadius: 999,
        background: c.bg,
        color: c.fg,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: 0.4,
      }}
    >
      {status}
    </span>
  );
}

function EvidenceChips({ refs }: { refs: EvidenceRef[] }) {
  if (!refs || refs.length === 0) return null;
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 6,
        marginTop: 6,
      }}
    >
      {refs.map((ref, i) => {
        const page = ref.page_number;
        const snippet =
          typeof ref.text_snippet === "string" ? ref.text_snippet : "";
        return (
          <span
            key={i}
            title={snippet}
            style={{
              fontSize: 10,
              padding: "2px 8px",
              borderRadius: 4,
              background: "#F1F5F9",
              color: "#334155",
              fontFamily: "monospace",
              border: `1px solid ${chrome.border}`,
              cursor: snippet ? "help" : "default",
            }}
          >
            {page !== undefined ? `p. ${page}` : `ref ${i + 1}`}
          </span>
        );
      })}
    </div>
  );
}

/**
 * Renders the TI Hub-parity metadata block under each flag / requirement:
 * AI explanation, structured evidence chips, existing reviews, and the
 * approve/reject/escalate action trio when the flag is still open.
 *
 * `onReview` is optional — requirements reuse the aiExplanation+evidence
 * subset without the review workflow.
 */
function FlagMeta({
  kind,
  id,
  aiExplanation,
  evidenceRefs,
  status,
  reviews,
  onReview,
}: {
  kind: FlagKind;
  id: string;
  aiExplanation: string | null;
  evidenceRefs: EvidenceRef[];
  status?: FlagStatus;
  reviews?: ReviewOut[];
  onReview?: ReviewHandler;
}) {
  const [busy, setBusy] = useState<ReviewDecision | null>(null);

  const hasMeta =
    Boolean(aiExplanation) ||
    (evidenceRefs && evidenceRefs.length > 0) ||
    (reviews && reviews.length > 0) ||
    (status === "open" && onReview);
  if (!hasMeta) return null;

  const handle = async (d: ReviewDecision) => {
    if (!onReview || busy) return;
    setBusy(d);
    try {
      await onReview(kind, id, d);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      style={{
        marginTop: 8,
        padding: "8px 10px",
        borderRadius: 6,
        background: "#FAFAF9",
        border: `1px solid ${chrome.border}`,
      }}
    >
      {aiExplanation && (
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: "#0369A1",
              letterSpacing: 0.5,
              marginBottom: 3,
            }}
          >
            AI EXPLANATION
          </div>
          <p
            style={{
              margin: 0,
              fontSize: 12,
              color: chrome.charcoal,
              lineHeight: 1.55,
            }}
          >
            {aiExplanation}
          </p>
        </div>
      )}
      {evidenceRefs && evidenceRefs.length > 0 && (
        <EvidenceChips refs={evidenceRefs} />
      )}
      {reviews && reviews.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: chrome.mutedFg,
              letterSpacing: 0.5,
              marginBottom: 4,
            }}
          >
            REVIEWS
          </div>
          {reviews.map((r) => (
            <div
              key={r.id}
              style={{
                fontSize: 11,
                color: chrome.charcoal,
                lineHeight: 1.5,
              }}
            >
              <strong style={{ textTransform: "uppercase" }}>{r.decision}</strong>
              {r.reason_code && ` · ${r.reason_code}`}
              {r.notes && ` — ${r.notes}`}
            </div>
          ))}
        </div>
      )}
      {status === "open" && onReview && (
        <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
          {(["approve", "escalate", "reject"] as ReviewDecision[]).map((d) => (
            <button
              key={d}
              type="button"
              disabled={busy !== null}
              onClick={() => void handle(d)}
              style={{
                fontSize: 11,
                padding: "4px 10px",
                borderRadius: 4,
                border: `1px solid ${chrome.border}`,
                background: busy === d ? "#E5E7EB" : "#FFFFFF",
                color: chrome.charcoal,
                cursor: busy !== null ? "wait" : "pointer",
                fontWeight: 600,
                textTransform: "capitalize",
              }}
            >
              {busy === d ? "…" : d}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ScheduleBSection({
  standard,
  specific,
  onReview,
}: {
  standard: ExceptionOut[];
  specific: ExceptionOut[];
  onReview?: ReviewHandler;
}) {
  const [open, setOpen] = useState(true);
  const [stdOpen, setStdOpen] = useState(false);
  const [specOpen, setSpecOpen] = useState(true);
  const total = standard.length + specific.length;

  return (
    <div style={cardOuter}>
      <SectionHeader
        title="Schedule B — Exceptions from Coverage"
        subtitle="Items excluded from title insurance coverage"
        count={total}
        collapsed={!open}
        onToggle={() => setOpen((o) => !o)}
      />
      {open && (
        <div>
          <SubsectionHeader
            title="3.1 Standard Exceptions"
            subtitle="Pre-printed exceptions common to all title insurance policies"
            count={standard.length}
            collapsed={!stdOpen}
            onToggle={() => setStdOpen((o) => !o)}
          />
          {stdOpen &&
            standard.map((e) => (
              <ExceptionRow key={e.id} item={e} onReview={onReview} />
            ))}
          <SubsectionHeader
            title="3.2 Specific Exceptions"
            subtitle="Property-specific exceptions identified from the title search"
            count={specific.length}
            collapsed={!specOpen}
            onToggle={() => setSpecOpen((o) => !o)}
          />
          {specOpen &&
            specific.map((e) => (
              <ExceptionRow key={e.id} item={e} onReview={onReview} />
            ))}
        </div>
      )}
    </div>
  );
}

/**
 * Deterministic final recommendation (approve / escalate / reject) rolled
 * up from all open flags. Mirrors TI Hub's RecommendationResponse. Pulled
 * from a dedicated endpoint because the backend reflects closed-flag
 * state (closed flags drop out of the rollup).
 */
function RecommendationBanner({
  packetId,
  token,
}: {
  packetId: string;
  token: string | null;
}) {
  const [rec, setRec] = useState<RecommendationResponse | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const payload = await api<RecommendationResponse>(
          `/api/packets/${packetId}/title-exam/recommendation`,
          { token },
        );
        if (!cancelled) setRec(payload);
      } catch {
        if (!cancelled) setRec(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [packetId, token]);

  if (!rec) return null;

  const theme: Record<
    ReviewDecision,
    { bg: string; fg: string; border: string; label: string }
  > = {
    approve: { bg: "#DCFCE7", fg: "#14532D", border: "#16A34A", label: "Approve" },
    escalate: { bg: "#FEF3C7", fg: "#78350F", border: "#D97706", label: "Escalate" },
    reject: { bg: "#FEE2E2", fg: "#7F1D1D", border: "#DC2626", label: "Reject" },
  };
  const t = theme[rec.decision];
  const confPct = Math.round(rec.confidence * 100);

  return (
    <div
      style={{
        background: t.bg,
        borderLeft: `4px solid ${t.border}`,
        borderRadius: 8,
        padding: "14px 18px",
        marginBottom: 16,
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 1,
          color: t.fg,
          textTransform: "uppercase",
        }}
      >
        AI recommendation
      </div>
      <div
        style={{
          fontSize: 14,
          fontWeight: 700,
          color: t.fg,
          textTransform: "uppercase",
          letterSpacing: 0.4,
        }}
      >
        {t.label}
      </div>
      <div style={{ fontSize: 12, color: t.fg, flex: 1 }}>{rec.reasoning}</div>
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: t.fg,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {confPct}% confidence
      </div>
    </div>
  );
}

function ScheduleCSection({ requirements }: { requirements: RequirementOut[] }) {
  const [open, setOpen] = useState(false);
  if (requirements.length === 0) return null;
  return (
    <div style={cardOuter}>
      <SectionHeader
        title="Schedule C — Requirements & Conditions"
        subtitle="Conditions that must be satisfied before policy issuance"
        count={requirements.length}
        collapsed={!open}
        onToggle={() => setOpen((o) => !o)}
      />
      {open && (
        <div>
          {requirements.map((r) => (
            <div
              key={r.id}
              style={{
                display: "flex",
                gap: 12,
                padding: "12px 20px",
                borderBottom: `1px solid ${chrome.border}`,
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  fontFamily: "monospace",
                  color: chrome.mutedFg,
                  minWidth: 28,
                  textAlign: "right",
                  paddingTop: 1,
                }}
              >
                {r.number}.
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{ fontSize: 13, fontWeight: 600, color: chrome.charcoal }}
                  >
                    {r.title}
                  </span>
                  <PriorityBadge priority={r.priority} />
                  {r.page_ref && (
                    <span
                      style={{
                        fontSize: 10,
                        color: chrome.mutedFg,
                        fontFamily: "monospace",
                      }}
                    >
                      {r.page_ref}
                    </span>
                  )}
                </div>
                <p
                  style={{
                    margin: "4px 0 0",
                    fontSize: 12,
                    color: chrome.mutedFg,
                    lineHeight: 1.55,
                  }}
                >
                  {r.description}
                </p>
                <span
                  style={{
                    fontSize: 11,
                    color: "#78716C",
                    marginTop: 4,
                    display: "inline-block",
                  }}
                >
                  Status:{" "}
                  <span style={{ fontWeight: 600 }}>
                    {STATUS_LABEL[r.status] ?? r.status}
                  </span>
                </span>
                {r.note && (
                  <p
                    style={{
                      margin: "6px 0 0",
                      fontSize: 11,
                      color: "#78716C",
                      fontStyle: "italic",
                      lineHeight: 1.55,
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 600,
                        fontStyle: "normal",
                        color: chrome.mutedFg,
                      }}
                    >
                      Note:
                    </span>{" "}
                    {r.note}
                  </p>
                )}
                {/* Requirements carry ai_explanation + evidence but have no
                    review workflow — FlagMeta omits the action buttons when
                    onReview is not supplied. */}
                <FlagMeta
                  kind="exception"
                  id={r.id}
                  aiExplanation={r.ai_explanation}
                  evidenceRefs={r.evidence_refs}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WarningsSection({
  warnings,
  onReview,
}: {
  warnings: WarningOut[];
  onReview?: ReviewHandler;
}) {
  const [open, setOpen] = useState(false);
  if (warnings.length === 0) return null;
  return (
    <div style={cardOuter}>
      <SectionHeader
        title="Key Warnings & Examiner's Notes"
        subtitle="Risk items flagged during title examination"
        count={warnings.length}
        collapsed={!open}
        onToggle={() => setOpen((o) => !o)}
      />
      {open && (
        <div>
          {warnings.map((w) => (
            <div
              key={w.id}
              style={{
                display: "flex",
                gap: 12,
                padding: "14px 20px",
                borderBottom: `1px solid ${chrome.border}`,
              }}
            >
              <SevBadge severity={w.severity} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: chrome.charcoal,
                    }}
                  >
                    {w.title}
                  </span>
                  {w.flag_type && <FlagTypeBadge flagType={w.flag_type} />}
                  <FlagStatusBadge status={w.status} />
                </div>
                <p
                  style={{
                    margin: "4px 0 0",
                    fontSize: 12,
                    color: chrome.mutedFg,
                    lineHeight: 1.55,
                  }}
                >
                  {w.description}
                </p>
                {w.note && (
                  <p
                    style={{
                      margin: "6px 0 0",
                      fontSize: 11,
                      color: "#78716C",
                      fontStyle: "italic",
                      lineHeight: 1.55,
                    }}
                  >
                    <span
                      style={{
                        fontWeight: 600,
                        fontStyle: "normal",
                        color: chrome.mutedFg,
                      }}
                    >
                      Note:
                    </span>{" "}
                    {w.note}
                  </p>
                )}
                <FlagMeta
                  kind="warning"
                  id={w.id}
                  aiExplanation={w.ai_explanation}
                  evidenceRefs={w.evidence_refs}
                  status={w.status}
                  reviews={w.reviews}
                  onReview={onReview}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ChecklistSection({
  items,
  progress,
  onToggle,
}: {
  items: ChecklistItemOut[];
  progress: ChecklistProgress;
  onToggle: (id: string, next: boolean) => void;
}) {
  const [open, setOpen] = useState(true);
  const hasNotes = items.some((i) => i.note);
  const pct =
    progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 0;

  return (
    <div style={cardOuter}>
      <SectionHeader
        title="Curative Checklist"
        subtitle="Actions required to clear title before policy issuance"
        count={items.length}
        collapsed={!open}
        onToggle={() => setOpen((o) => !o)}
        right={
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              fontSize: 11,
              color: "#78350F",
              fontWeight: 600,
            }}
          >
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              {progress.completed} / {progress.total}
            </span>
            <div
              style={{
                width: 80,
                height: 6,
                background: "#FCD34D40",
                borderRadius: 3,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: chrome.amber,
                  transition: "width 0.25s",
                }}
              />
            </div>
          </div>
        }
      />
      {open && (
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <thead>
            <tr
              style={{
                borderBottom: `1px solid ${chrome.border}`,
                background: "#FAFAF8",
              }}
            >
              <th style={thStyle}>✓</th>
              <th style={{ ...thStyle, width: 44 }}>#</th>
              <th style={{ ...thStyle, textAlign: "left" }}>Action required</th>
              <th style={{ ...thStyle, width: 120 }}>Priority</th>
              <th style={{ ...thStyle, width: 90, textAlign: "center" }}>Status</th>
              {hasNotes && <th style={{ ...thStyle, textAlign: "left" }}>Notes</th>}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.id}
                style={{ borderBottom: `1px solid ${chrome.border}` }}
              >
                <td style={{ padding: "10px 20px", width: 44 }}>
                  <input
                    type="checkbox"
                    checked={item.checked}
                    onChange={(e) => onToggle(item.id, e.target.checked)}
                    style={{
                      width: 16,
                      height: 16,
                      cursor: "pointer",
                      accentColor: chrome.amberDark,
                    }}
                    aria-label={`Mark "${item.action}" ${item.checked ? "incomplete" : "complete"}`}
                  />
                </td>
                <td
                  style={{
                    padding: "10px 12px",
                    fontFamily: "monospace",
                    color: chrome.mutedFg,
                    fontSize: 12,
                    width: 44,
                  }}
                >
                  {item.number}
                </td>
                <td
                  style={{
                    padding: "10px 12px",
                    fontSize: 13,
                    color: chrome.charcoal,
                    textDecoration: item.checked ? "line-through" : "none",
                    opacity: item.checked ? 0.7 : 1,
                  }}
                >
                  {item.action}
                </td>
                <td style={{ padding: "10px 12px", width: 120 }}>
                  <PriorityBadge priority={item.priority} />
                </td>
                <td
                  style={{
                    padding: "10px 12px",
                    textAlign: "center",
                    width: 90,
                  }}
                >
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: item.checked ? "#059669" : chrome.mutedFg,
                    }}
                  >
                    {item.checked ? "✓ Done" : "Pending"}
                  </span>
                </td>
                {hasNotes && (
                  <td
                    style={{
                      padding: "10px 12px",
                      fontSize: 11,
                      color: chrome.mutedFg,
                      fontStyle: "italic",
                    }}
                  >
                    {item.note || ""}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/* ----- Results tab ---------------------------------------------------- */

function ResultsTab({
  data,
  onReviewFlag,
}: {
  data: TitleExamDashboard;
  onReviewFlag: ReviewHandler;
}) {
  if (data.specific_exceptions.length === 0) {
    return (
      <div style={cardStyle}>
        <p style={emptyStyle}>No specific exceptions to review.</p>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <p style={{ fontSize: 12, color: chrome.mutedFg, margin: 0 }}>
        Detailed view of Schedule B specific exceptions — the findings that
        require underwriter judgment.
      </p>
      {data.specific_exceptions.map((e) => (
        <div key={e.id} style={cardStyle}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 8,
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontFamily: "monospace",
                fontSize: 12,
                color: chrome.mutedFg,
              }}
            >
              B-{e.number}
            </span>
            <span
              style={{
                fontSize: 15,
                fontWeight: 700,
                color: chrome.charcoal,
              }}
            >
              {e.title}
            </span>
            <SevBadge severity={e.severity} />
            {e.flag_type && <FlagTypeBadge flagType={e.flag_type} />}
            <FlagStatusBadge status={e.status} />
            {e.page_ref && (
              <span
                style={{
                  fontSize: 10,
                  fontFamily: "monospace",
                  color: chrome.mutedFg,
                }}
              >
                {e.page_ref}
              </span>
            )}
          </div>
          <p
            style={{
              margin: "0 0 10px",
              fontSize: 13,
              color: chrome.charcoal,
              lineHeight: 1.55,
            }}
          >
            {e.description}
          </p>
          {e.note && (
            <div
              style={{
                background: chrome.amberBg,
                border: `1px solid ${chrome.amberLight}`,
                borderLeft: `3px solid ${chrome.amber}`,
                borderRadius: 6,
                padding: "8px 12px",
                fontSize: 12,
                color: "#78350F",
                lineHeight: 1.55,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: 0.5,
                  textTransform: "uppercase",
                  marginRight: 6,
                }}
              >
                Examiner note
              </span>
              {e.note}
            </div>
          )}
          <FlagMeta
            kind="exception"
            id={e.id}
            aiExplanation={e.ai_explanation}
            evidenceRefs={e.evidence_refs}
            status={e.status}
            reviews={e.reviews}
            onReview={onReviewFlag}
          />
        </div>
      ))}
    </div>
  );
}

/* ----- Pages tab ------------------------------------------------------ */

function PagesTab() {
  return (
    <div
      style={{
        ...cardStyle,
        textAlign: "center",
        padding: "48px 28px",
      }}
    >
      <div
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: chrome.charcoal,
          marginBottom: 6,
        }}
      >
        Document viewer
      </div>
      <div style={{ fontSize: 12, color: chrome.mutedFg }}>
        Source pages with OCR overlay render here in production.
      </div>
    </div>
  );
}

/* ----- Export tab ----------------------------------------------------- */

function ExportTab({ data }: { data: TitleExamDashboard }) {
  const items = [
    `ALTA exception classification for all ${data.specific_exceptions.length} specific exceptions`,
    `Schedule B/C analysis (${data.standard_exceptions.length + data.specific_exceptions.length} exceptions, ${data.requirements.length} requirements)`,
    "Vesting analysis and defect detection",
    `Curative checklist (${data.checklist.length} actions, ${data.checklist_progress.completed} complete)`,
    "Marketability assessment",
    "Title insurance requirements",
    "Source document page references",
    "Examiner warnings & notes",
  ];
  return (
    <div
      style={{
        ...cardStyle,
        padding: 0,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          background: `linear-gradient(135deg, ${chrome.amberBg}, ${chrome.amberLight}66)`,
          padding: "24px 28px",
          display: "flex",
          alignItems: "center",
          gap: 16,
          borderBottom: `1px solid ${chrome.amberLight}`,
        }}
      >
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 12,
            background: `linear-gradient(135deg, ${chrome.amberLight}, ${chrome.amber}66)`,
            border: `1px solid ${chrome.amberLight}`,
            color: chrome.amberDark,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
        </div>
        <div>
          <h2
            style={{
              fontSize: 16,
              fontWeight: 700,
              margin: "0 0 4px",
              color: chrome.charcoal,
            }}
          >
            Title examination report
          </h2>
          <p style={{ fontSize: 12, color: chrome.mutedFg, margin: 0 }}>
            ALTA-compliant exception schedule with curative actions
          </p>
        </div>
      </div>
      <div style={{ padding: "18px 28px" }}>
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: chrome.mutedFg,
            letterSpacing: 1,
            textTransform: "uppercase",
            marginBottom: 12,
          }}
        >
          Report includes
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 8,
          }}
        >
          {items.map((item) => (
            <div
              key={item}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                fontSize: 13,
                color: chrome.charcoal,
              }}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="#059669"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
              {item}
            </div>
          ))}
        </div>
      </div>
      <div
        style={{
          padding: "16px 28px",
          borderTop: `1px solid ${chrome.border}`,
          background: `${chrome.muted}80`,
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
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
  );
}

/* ----- shared styles -------------------------------------------------- */

const titleStyle: React.CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  color: chrome.charcoal,
  margin: "0 0 16px",
  fontFamily: typography.fontFamily.primary,
};

const emptyStyle: React.CSSProperties = {
  fontSize: 13,
  color: chrome.mutedFg,
  margin: 0,
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

const cardStyle: React.CSSProperties = {
  background: chrome.card,
  borderRadius: 12,
  border: `1px solid ${chrome.border}`,
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
  padding: "20px 24px",
};

const cardOuter: React.CSSProperties = {
  borderRadius: 12,
  border: `1px solid ${chrome.border}`,
  background: chrome.card,
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
  overflow: "hidden",
};

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "9px 12px",
  fontSize: 10,
  fontWeight: 600,
  color: chrome.mutedFg,
  textTransform: "uppercase",
  letterSpacing: 0.5,
};
