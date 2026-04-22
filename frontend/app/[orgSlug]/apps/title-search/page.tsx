"use client";

/**
 * Title Search & Abstraction micro-app page (US-6.1).
 *
 * Five tabs matching the one-logikality-demo reference 1:1:
 *  - Overview — summary bullets + severity KPI cards (crit/high/med/low)
 *  - Chain of Title — ordered ownership links with gap highlight
 *  - Flags — 7 risk findings, each expandable into AI note + MISMO +
 *    evidence + cross-app ref (Phase 7 primitives inline)
 *  - Property — nested property summary (ID / physical / ownership /
 *    mortgages / liens / easements / taxes / insurance)
 *  - Package — PDF / MISMO XML export surface
 *
 * Data source: GET /api/packets/{id}/title-search. The ECV launcher
 * routes here when the org is subscribed+enabled AND title-search is
 * `ready`. Server re-checks the subscription so a deep link can't skip
 * the gate.
 */

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

/* ----- types ---------------------------------------------------------- */

type Severity = "critical" | "high" | "medium" | "low";
type Decision = "approve" | "reject" | "escalate";

type MismoField = {
  entity: string;
  field: string;
  value: string;
  confidence: number;
};

type AiRec = {
  decision: Decision;
  confidence: number;
  reasoning: string;
};

type Evidence = { page: number; snippet: string };
type CrossApp = { app: string; section: string; note: string };
type Source = { doc_type: string; pages: number[] };

type Flag = {
  id: string;
  number: number;
  severity: Severity;
  flag_type: string;
  title: string;
  description: string;
  page_ref: string;
  ai_note: string | null;
  ai_rec: AiRec | null;
  mismo: MismoField[];
  source: Source;
  cross_app: CrossApp | null;
  evidence: Evidence[];
};

type SeverityCounts = {
  critical: number;
  high: number;
  medium: number;
  low: number;
  total: number;
};

type PropertySummary = Record<string, unknown>;

type TitleSearchDashboard = {
  severity_counts: SeverityCounts;
  flags: Flag[];
  property_summary: PropertySummary;
};

type Tab = "overview" | "chain" | "flags" | "property" | "package";

/* ----- palette -------------------------------------------------------- */

const SUCCESS = "#10B981";
const SUCCESS_BG = "#D1FAE5";
const DESTRUCTIVE = "#DC2626";
const DESTRUCTIVE_BG = "#FEE2E2";

const SEV_COLORS: Record<Severity, { bg: string; text: string; badge: string; border: string }> = {
  critical: { bg: "#FEE2E2", text: "#991B1B", badge: "#DC2626", border: "#FCA5A5" },
  high: { bg: "#FEF3C7", text: "#78350F", badge: "#D97706", border: "#FCD34D" },
  medium: { bg: "#FEF9C3", text: "#713F12", badge: "#CA8A04", border: "#FDE68A" },
  low: { bg: "#DBEAFE", text: "#1E3A8A", badge: "#2563EB", border: "#93C5FD" },
};

const SEV_NAMES: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

/* ----- page ----------------------------------------------------------- */

export default function TitleSearchPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const searchParams = useSearchParams();
  const packetId = searchParams.get("packet");
  const router = useRouter();
  const { ready } = useRequireRole(["customer_admin", "customer_user"], `/${orgSlug}`);
  const { token } = useAuth();

  const [data, setData] = useState<TitleSearchDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token || !packetId) return;
    let cancelled = false;
    (async () => {
      try {
        const payload = await api<TitleSearchDashboard>(
          `/api/packets/${packetId}/title-search`,
          { token },
        );
        if (!cancelled) setData(payload);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          setError("The Title Search & Abstraction app is not enabled for your organization.");
        } else if (err instanceof ApiError && err.status === 409) {
          setError("Title findings are still being computed. Check back shortly.");
        } else if (err instanceof ApiError && err.status === 404) {
          setError("Packet not found.");
        } else {
          setError("Couldn't load title-search analysis.");
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
        <h1 style={titleStyle}>Title Search &amp; Abstraction</h1>
        <p style={emptyStyle}>Open a packet from the ECV dashboard to run a title search.</p>
        <Link href={`/${orgSlug}/upload`} style={linkBtnStyle}>
          Upload a packet
        </Link>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: 800 }}>
        <h1 style={titleStyle}>Title Search &amp; Abstraction</h1>
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
        <h1 style={titleStyle}>Title Search &amp; Abstraction</h1>
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
  data: TitleSearchDashboard;
  orgSlug: string;
  packetId: string;
}) {
  const { severity_counts: counts, flags, property_summary: ps } = data;
  const [tab, setTab] = useState<Tab>("overview");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState<Record<string, Decision>>({});

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
          <h1 style={{ ...titleStyle, margin: "0 0 6px" }}>Title search &amp; abstraction</h1>
          <div style={{ display: "flex", gap: 16, fontSize: 12, color: chrome.mutedFg }}>
            <span>
              Packet:{" "}
              <strong style={{ color: chrome.charcoal, fontFamily: "monospace" }}>
                {packetId.slice(0, 8)}
              </strong>
            </span>
            <span>
              Standard: <strong style={{ color: chrome.charcoal }}>ALTA 2021</strong>
            </span>
            <span>
              Flags: <strong style={{ color: chrome.charcoal }}>{counts.total}</strong>
            </span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href={`/${orgSlug}/ecv?packet=${packetId}`} style={secondaryBtnStyle}>
            Back to ECV
          </Link>
          <button type="button" style={ctaBtnStyle} onClick={() => setTab("package")}>
            Export package
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
            { key: "chain", label: "Chain of Title" },
            { key: "flags", label: "Flags" },
            { key: "property", label: "Property" },
            { key: "package", label: "Package" },
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
          counts={counts}
          onGoFlags={() => setTab("flags")}
          onGoPackage={() => setTab("package")}
        />
      )}
      {tab === "chain" && <ChainTab ps={ps} />}
      {tab === "flags" && (
        <FlagsTab
          flags={flags}
          counts={counts}
          expandedId={expandedId}
          onToggle={(id) => setExpandedId((prev) => (prev === id ? null : id))}
          reviewed={reviewed}
          onDecide={(id, decision) => setReviewed((prev) => ({ ...prev, [id]: decision }))}
        />
      )}
      {tab === "property" && <PropertyTab ps={ps} />}
      {tab === "package" && <PackageTab counts={counts} />}
    </div>
  );
}

/* ----- Overview ------------------------------------------------------- */

function OverviewTab({
  counts,
  onGoFlags,
  onGoPackage,
}: {
  counts: SeverityCounts;
  onGoFlags: () => void;
  onGoPackage: () => void;
}) {
  const bullets = [
    `Title commitment analysis identified ${counts.total} open items requiring attention before closing.`,
    `${counts.critical} critical defects must be resolved: unreleased mortgage from First National Bank ($312,000) and a 4-year gap in the chain of title (2008–2012).`,
    `${counts.high} high-priority items: non-standard utility easement and name discrepancy between deed and commitment.`,
    "Chain of title traced back 30 years across 4 documented ownership links.",
    "Tax status shows $2,847 in delinquent property taxes that must be resolved at closing.",
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
        {/* LEFT: summary bullets */}
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
            <span style={{ fontSize: 16 }}>✦</span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: chrome.mutedFg,
                letterSpacing: 1,
                textTransform: "uppercase",
              }}
            >
              Title search summary
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

        {/* RIGHT: severity KPI cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {(["critical", "high", "medium", "low"] as const).map((sev) => {
            const s = SEV_COLORS[sev];
            const n = counts[sev];
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
                  <div style={{ fontSize: 11, color: s.text, opacity: 0.7, marginTop: 2 }}>
                    {n} {n === 1 ? "item" : "items"}
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
                  {n}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
        <button type="button" onClick={onGoFlags} style={secondaryBtnStyle}>
          View all flags
        </button>
        <button type="button" onClick={onGoPackage} style={ctaBtnStyle}>
          View detailed results →
        </button>
      </div>
    </div>
  );
}

/* ----- Chain of Title ------------------------------------------------- */

type ChainDeed = {
  deed_type: string;
  recording_date: string;
  grantor: string;
  grantee: string;
  consideration: number;
  recording_ref: string;
};

function ChainTab({ ps }: { ps: PropertySummary }) {
  const chain = ((ps.chain_of_title as ChainDeed[] | undefined) ?? []).slice();
  // Sort oldest → newest for the visual chain (chain_of_title is stored
  // newest-first to mirror how title reports list recordings).
  chain.sort((a, b) => a.recording_date.localeCompare(b.recording_date));

  type Link = {
    pos: number;
    from: string;
    to: string;
    date: string;
    type: string;
    gap: boolean;
    gapDesc?: string;
  };
  const links: Link[] = chain.map((d, i) => ({
    pos: i + 1,
    from: d.grantor,
    to: d.grantee,
    date: d.recording_date,
    type: d.deed_type,
    // Heuristic: if the previous recording and this one span more than
    // 3 years, flag a gap. Matches the 2008 → 2012 gap in the canned
    // data without us having to hard-code it.
    gap:
      i > 0 &&
      new Date(d.recording_date).getFullYear() -
        new Date(chain[i - 1].recording_date).getFullYear() >
        3,
    gapDesc:
      i > 0 &&
      new Date(d.recording_date).getFullYear() -
        new Date(chain[i - 1].recording_date).getFullYear() >
        3
        ? `${new Date(d.recording_date).getFullYear() - new Date(chain[i - 1].recording_date).getFullYear()}-year gap since previous recording`
        : undefined,
  }));

  const gapCount = links.filter((l) => l.gap).length;

  return (
    <div style={{ paddingTop: 8 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <h3
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: chrome.mutedFg,
            textTransform: "uppercase",
            letterSpacing: 1,
            margin: 0,
          }}
        >
          Chain of Title
        </h3>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {gapCount > 0 && (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                borderRadius: 12,
                background: "#FEF3C7",
                padding: "2px 10px",
                fontSize: 11,
                fontWeight: 600,
                color: "#78350F",
                border: "1px solid #FCD34D",
              }}
            >
              ⚠ {gapCount} gap{gapCount === 1 ? "" : "s"}
            </span>
          )}
          <span style={{ fontSize: 11, color: chrome.mutedFg }}>{links.length} links</span>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {links.map((link, i) => (
          <div key={i}>
            <div
              style={{
                background: link.gap ? "#FEF3C740" : chrome.card,
                borderRadius: 10,
                border: `1px solid ${link.gap ? "#FCD34D" : chrome.border}`,
                padding: "12px 16px",
                display: "flex",
                alignItems: "center",
                gap: 14,
                boxShadow: "0 1px 3px rgba(20,18,14,0.03)",
              }}
            >
              <div
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 13,
                  fontWeight: 700,
                  background: link.gap ? "#FEF3C7" : chrome.muted,
                  color: link.gap ? "#92400E" : chrome.mutedFg,
                  border: link.gap ? "1px solid #FCD34D" : "none",
                  fontVariantNumeric: "tabular-nums",
                  flexShrink: 0,
                }}
              >
                {link.pos}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 14,
                    flexWrap: "wrap",
                  }}
                >
                  <span style={{ fontWeight: 500, color: chrome.charcoal }}>{link.from}</span>
                  <span style={{ color: chrome.mutedFg, fontSize: 12 }}>→</span>
                  <span style={{ fontWeight: 500, color: chrome.charcoal }}>{link.to}</span>
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    marginTop: 4,
                    fontSize: 11,
                    color: chrome.mutedFg,
                    alignItems: "center",
                    flexWrap: "wrap",
                  }}
                >
                  <span>{link.date}</span>
                  <span
                    style={{
                      background: chrome.muted,
                      padding: "1px 8px",
                      borderRadius: 12,
                      fontSize: 10,
                    }}
                  >
                    {link.type}
                  </span>
                  {link.gap && link.gapDesc && (
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                        background: "#FEF3C7",
                        padding: "1px 8px",
                        borderRadius: 12,
                        color: "#78350F",
                        fontWeight: 600,
                        fontSize: 10,
                      }}
                    >
                      ⚠ {link.gapDesc}
                    </span>
                  )}
                </div>
              </div>
            </div>
            {i < links.length - 1 && (
              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  padding: "2px 0",
                  color: chrome.mutedFg,
                  fontSize: 12,
                }}
              >
                ↓
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ----- Flags ---------------------------------------------------------- */

function FlagsTab({
  flags,
  counts,
  expandedId,
  onToggle,
  reviewed,
  onDecide,
}: {
  flags: Flag[];
  counts: SeverityCounts;
  expandedId: string | null;
  onToggle: (id: string) => void;
  reviewed: Record<string, Decision>;
  onDecide: (id: string, decision: Decision) => void;
}) {
  return (
    <div style={{ paddingTop: 8 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <h3
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: chrome.mutedFg,
            textTransform: "uppercase",
            letterSpacing: 1,
            margin: 0,
          }}
        >
          Flags ({counts.total})
        </h3>
        <div style={{ display: "flex", gap: 6 }}>
          {(["critical", "high", "medium", "low"] as const).map((sev) => (
            <SevPill key={sev} severity={sev} />
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gap: 10 }}>
        {flags.map((flag) => {
          const expanded = expandedId === flag.id;
          const decision = reviewed[flag.id];
          return (
            <div
              key={flag.id}
              style={{
                background: chrome.card,
                borderRadius: 10,
                border: `1px solid ${chrome.border}`,
                boxShadow: "0 1px 3px rgba(20,18,14,0.03)",
                overflow: "hidden",
              }}
            >
              {/* Header row */}
              <div
                style={{
                  padding: "14px 18px",
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 16,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      flexWrap: "wrap",
                    }}
                  >
                    <span style={{ color: chrome.mutedFg, fontSize: 14 }}>⚠</span>
                    <span style={{ fontWeight: 500, color: chrome.charcoal, fontSize: 14 }}>
                      {flag.title}
                    </span>
                    <SevPill severity={flag.severity} />
                    {decision && (
                      <span
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          borderRadius: 12,
                          padding: "2px 9px",
                          fontSize: 10,
                          fontWeight: 600,
                          background:
                            decision === "approve"
                              ? "#D1FAE5"
                              : decision === "reject"
                                ? "#FEE2E2"
                                : "#FEF3C7",
                          color:
                            decision === "approve"
                              ? "#065F46"
                              : decision === "reject"
                                ? "#991B1B"
                                : "#78350F",
                          textTransform: "capitalize",
                        }}
                      >
                        {decision}d
                      </span>
                    )}
                  </div>
                  <p
                    style={{
                      fontSize: 13,
                      color: chrome.mutedFg,
                      margin: "6px 0 0",
                      lineHeight: 1.5,
                    }}
                  >
                    {flag.description}
                  </p>
                  <p
                    style={{
                      fontSize: 11,
                      color: chrome.mutedFg,
                      margin: "4px 0 0",
                      opacity: 0.8,
                    }}
                  >
                    {flag.flag_type} · {flag.page_ref}
                  </p>
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  {!decision && (
                    <>
                      <button
                        type="button"
                        onClick={() => onDecide(flag.id, "approve")}
                        title="Approve"
                        style={iconBtn(SUCCESS_BG, "#059669")}
                      >
                        ✓
                      </button>
                      <button
                        type="button"
                        onClick={() => onDecide(flag.id, "reject")}
                        title="Reject"
                        style={iconBtn(DESTRUCTIVE_BG, "#DC2626")}
                      >
                        ✕
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => onToggle(flag.id)}
                    style={{
                      padding: "4px 12px",
                      fontSize: 11,
                      fontWeight: 600,
                      borderRadius: 16,
                      border: `1px solid ${chrome.border}`,
                      background: expanded ? chrome.muted : "#fff",
                      color: chrome.charcoal,
                      cursor: "pointer",
                    }}
                  >
                    {expanded ? "Hide review" : "Review"}
                  </button>
                </div>
              </div>

              {/* Expanded review panel (Phase 7 primitives) */}
              {expanded && (
                <div
                  style={{
                    borderTop: `1px solid ${chrome.border}`,
                    background: chrome.bg,
                    padding: "16px 18px",
                  }}
                >
                  {flag.ai_note && <AiNoteCallout label="AI analyst note" note={flag.ai_note} />}
                  {flag.ai_rec && <AiRecommendationBlock rec={flag.ai_rec} />}
                  <MismoPanel fields={flag.mismo} />
                  <EvidencePanel source={flag.source} evidence={flag.evidence} />
                  {flag.cross_app && <CrossAppRef link={flag.cross_app} />}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function iconBtn(hoverBg: string, hoverColor: string): React.CSSProperties {
  // Static style — the one-logikality-demo animates these on hover with
  // JS handlers; for the production port we keep it simple since the
  // action semantics are identical.
  return {
    width: 28,
    height: 28,
    borderRadius: "50%",
    background: hoverBg,
    color: hoverColor,
    border: "none",
    cursor: "pointer",
    fontSize: 14,
    fontWeight: 700,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  };
}

function SevPill({ severity }: { severity: Severity }) {
  const c = SEV_COLORS[severity];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 12,
        border: `1px solid ${c.border}`,
        padding: "2px 10px",
        fontSize: 11,
        fontWeight: 700,
        background: c.bg,
        color: c.text,
        textTransform: "capitalize",
      }}
    >
      {severity}
    </span>
  );
}

/* ----- Property ------------------------------------------------------- */

type NamedEntity = { [k: string]: unknown };

const titleCase = (s: string) =>
  s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const formatValue = (v: unknown): string => {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return v.toLocaleString();
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
};

function PropertyTab({ ps }: { ps: PropertySummary }) {
  const sections: { key: string; title: string; kind: "grid" | "deed-list" | "entity-list" }[] =
    [
      { key: "property_identification", title: "Property identification", kind: "grid" },
      { key: "physical_attributes", title: "Physical attributes", kind: "grid" },
      { key: "lot_and_land", title: "Lot &amp; land / Zoning", kind: "grid" },
      { key: "current_ownership", title: "Current ownership", kind: "grid" },
      { key: "chain_of_title", title: "Chain of title", kind: "deed-list" },
      { key: "mortgages", title: "Mortgages", kind: "entity-list" },
      { key: "liens", title: "Liens &amp; judgments", kind: "entity-list" },
      { key: "easements", title: "Easements", kind: "entity-list" },
      { key: "restrictions", title: "Restrictions", kind: "entity-list" },
      { key: "taxes", title: "Taxes", kind: "grid" },
      { key: "title_insurance", title: "Title insurance", kind: "grid" },
    ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, paddingTop: 8 }}>
      {sections.map((sec) => {
        const data = ps[sec.key];
        if (!data) return null;
        return (
          <EntitySection key={sec.key} title={sec.title}>
            {sec.kind === "grid" && <GridEntries data={data as NamedEntity} />}
            {sec.kind === "deed-list" && <DeedList deeds={data as ChainDeed[]} />}
            {sec.kind === "entity-list" && <EntityList items={data as NamedEntity[]} />}
          </EntitySection>
        );
      })}
    </div>
  );
}

function EntitySection({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <div
      style={{
        background: chrome.card,
        borderRadius: 10,
        border: `1px solid ${chrome.border}`,
        boxShadow: "0 1px 3px rgba(20,18,14,0.03)",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px",
          background: open ? chrome.amberBg : "#fff",
          border: "none",
          cursor: "pointer",
          fontSize: 13,
          fontWeight: 600,
          color: chrome.charcoal,
          fontFamily: typography.fontFamily.primary,
        }}
      >
        <span dangerouslySetInnerHTML={{ __html: title }} />
        <span style={{ color: chrome.mutedFg, fontSize: 11 }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div style={{ padding: "14px 18px", borderTop: `1px solid ${chrome.border}` }}>
          {children}
        </div>
      )}
    </div>
  );
}

function GridEntries({ data }: { data: NamedEntity }) {
  const entries = Object.entries(data).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        gap: "10px 20px",
      }}
    >
      {entries.map(([k, v]) => (
        <div key={k}>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: chrome.mutedFg,
              letterSpacing: 0.5,
              textTransform: "uppercase",
              marginBottom: 2,
            }}
          >
            {titleCase(k)}
          </div>
          <div style={{ fontSize: 13, color: chrome.charcoal }}>{formatValue(v)}</div>
        </div>
      ))}
    </div>
  );
}

function DeedList({ deeds }: { deeds: ChainDeed[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {deeds.map((deed, i) => (
        <div
          key={i}
          style={{
            borderRadius: 8,
            border: `1px solid ${chrome.amberLight}`,
            background: `${chrome.amberBg}80`,
            padding: 12,
            fontSize: 13,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 4,
            }}
          >
            <span style={{ fontWeight: 600, color: chrome.charcoal }}>{deed.deed_type}</span>
            <span style={{ fontSize: 11, color: chrome.mutedFg }}>{deed.recording_date}</span>
          </div>
          <p style={{ color: chrome.mutedFg, margin: "0 0 4px", fontSize: 13 }}>
            {deed.grantor} → {deed.grantee}
          </p>
          <p style={{ fontSize: 11, color: chrome.mutedFg, margin: 0 }}>
            Consideration: ${deed.consideration.toLocaleString()} · Ref: {deed.recording_ref}
          </p>
        </div>
      ))}
    </div>
  );
}

function EntityList({ items }: { items: NamedEntity[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {items.map((item, i) => {
        const entries = Object.entries(item).filter(
          ([, v]) => v !== null && v !== undefined && v !== "",
        );
        return (
          <div
            key={i}
            style={{
              borderRadius: 8,
              border: `1px solid ${chrome.border}`,
              padding: 12,
              fontSize: 13,
              background: "#fff",
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                gap: "8px 16px",
              }}
            >
              {entries.map(([k, v]) => (
                <div key={k}>
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      color: chrome.mutedFg,
                      letterSpacing: 0.5,
                      textTransform: "uppercase",
                      marginBottom: 2,
                    }}
                  >
                    {titleCase(k)}
                  </div>
                  <div style={{ fontSize: 12, color: chrome.charcoal, lineHeight: 1.4 }}>
                    {formatValue(v)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ----- Package -------------------------------------------------------- */

function PackageTab({ counts }: { counts: SeverityCounts }) {
  return (
    <div style={{ paddingTop: 8 }}>
      <div
        style={{
          background: chrome.card,
          borderRadius: 12,
          border: `1px solid ${chrome.border}`,
          boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
          overflow: "hidden",
        }}
      >
        {/* Amber hero */}
        <div
          style={{
            background: `linear-gradient(135deg, ${chrome.amberBg}, ${chrome.amberLight}40)`,
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
              background: `linear-gradient(135deg, ${chrome.amberLight}, ${chrome.amber}40)`,
              border: `1px solid ${chrome.amberLight}`,
              color: chrome.amberDark,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 20,
              fontWeight: 700,
            }}
          >
            ⬢
          </div>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 4px", color: chrome.charcoal }}>
              Title search package
            </h2>
            <p style={{ fontSize: 12, color: chrome.mutedFg, margin: 0 }}>
              Complete report with property summary, chain of title, exceptions, and
              recommendations
            </p>
          </div>
        </div>

        {/* Package contents */}
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
            Package contents
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {[
              "Property summary & legal description",
              "Chain of title (4 links, 1 gap flagged)",
              "Liens & encumbrances (1 active)",
              "Tax status & assessments",
              "Easements & restrictions",
              `Flags & exceptions (${counts.total} items)`,
              "Examiner recommendations",
              "Source document citations",
            ].map((item) => (
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
                <span style={{ color: "#059669", fontWeight: 700 }}>✓</span> {item}
              </div>
            ))}
          </div>
        </div>

        {/* Action bar */}
        <div
          style={{
            padding: "16px 28px",
            borderTop: `1px solid ${chrome.border}`,
            background: `${chrome.muted}80`,
            display: "flex",
            gap: 8,
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ fontSize: 12, color: chrome.mutedFg }}>
            PDF format · Ready for download
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" style={ctaBtnStyle}>
              Download PDF
            </button>
            <button type="button" style={purpleBtnStyle}>
              MISMO XML
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ----- Phase 7 primitives (shared) ------------------------------------ */

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

function AiRecommendationBlock({ rec }: { rec: AiRec }) {
  const palette: Record<Decision, { bg: string; text: string; border: string; label: string }> = {
    approve: { bg: "#D1FAE5", text: "#065F46", border: "#86EFAC", label: "Approve" },
    reject: { bg: "#FEE2E2", text: "#991B1B", border: "#FCA5A5", label: "Reject" },
    escalate: { bg: "#FEF3C7", text: "#78350F", border: "#FCD34D", label: "Escalate" },
  };
  const c = palette[rec.decision];
  return (
    <div
      style={{
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: 6,
        padding: "10px 14px",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 11,
          fontWeight: 700,
          color: c.text,
          letterSpacing: 0.5,
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        <span>AI recommendation · {c.label}</span>
        <span
          style={{
            background: "#fff",
            color: c.text,
            padding: "1px 7px",
            borderRadius: 10,
            fontSize: 10,
            border: `1px solid ${c.border}`,
          }}
        >
          {rec.confidence}% confidence
        </span>
      </div>
      <div style={{ fontSize: 12, color: chrome.charcoal, lineHeight: 1.55 }}>{rec.reasoning}</div>
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
        background: "#fff",
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
          <span style={{ fontSize: 11, fontWeight: 600, color: chrome.charcoal }}>
            {f.value}
          </span>
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

function EvidencePanel({ source, evidence }: { source: Source; evidence: Evidence[] }) {
  if (evidence.length === 0) return null;
  return (
    <div
      style={{
        border: `1px solid ${chrome.border}`,
        borderRadius: 6,
        overflow: "hidden",
        marginBottom: 12,
        background: "#fff",
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
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>Source evidence</span>
        <span style={{ fontFamily: "monospace", fontSize: 10 }}>
          {source.doc_type} · p.{" "}
          {source.pages.join(", p. ")}
        </span>
      </div>
      {evidence.map((e, i) => (
        <div
          key={i}
          style={{
            padding: "8px 12px",
            fontSize: 11,
            borderTop: i === 0 ? "none" : `1px solid ${chrome.bg}`,
            display: "flex",
            gap: 10,
          }}
        >
          <span
            style={{
              fontFamily: "monospace",
              color: chrome.mutedFg,
              fontSize: 10,
              flexShrink: 0,
            }}
          >
            p. {e.page}
          </span>
          <span style={{ color: chrome.charcoal, lineHeight: 1.5 }}>&ldquo;{e.snippet}&rdquo;</span>
        </div>
      ))}
    </div>
  );
}

function CrossAppRef({ link: r }: { link: CrossApp }) {
  return (
    <div
      style={{
        border: `1px solid #BD33A4`,
        background: "#BD33A40C",
        borderRadius: 6,
        padding: "10px 14px",
        fontSize: 12,
        color: chrome.charcoal,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: "#BD33A4",
          letterSpacing: 0.5,
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        Cross-app reference → {r.app} · {r.section}
      </div>
      <div style={{ lineHeight: 1.55 }}>{r.note}</div>
    </div>
  );
}

/* ----- shared styles -------------------------------------------------- */

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
