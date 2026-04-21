"use client";

/**
 * ECV dashboard (US-3.5 – 3.10, 3.13).
 *
 * Loads /api/packets/{id}/ecv and renders:
 *  - Hero loan summary with overall-score gauge + 90% auto-approval banner
 *  - 3 KPI cards (documents / items-to-review / auto-verified)
 *  - 3 tabs: Documents (by category) / Section scores / Items-to-Review
 *  - Sticky action bar (Approve / Reject / Export PDF / Manual review)
 *
 * UX matches the one-logikality-demo reference 1:1. Items deferred to
 * later slices (not wired here): loan-program confirmation pill
 * (US-3.11), override dialog (US-3.12), blocked-app sidebar logic
 * (Phase 5), ConfigApplied badge (US-4.5), AI-note / MISMO / evidence
 * panels (Phase 7).
 */

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";
import { LOAN_PROGRAMS } from "@/lib/rules";

/* ----- types ---------------------------------------------------------- */

type Packet = {
  id: string;
  declared_program_id: string;
  status: string;
  current_stage: string | null;
  started_processing_at: string | null;
  completed_at: string | null;
  created_at: string;
};

type LineItem = {
  id: string;
  item_code: string;
  check: string;
  result: string;
  confidence: number;
};

type Section = {
  id: string;
  section_number: number;
  name: string;
  weight: number;
  score: number;
  line_items: LineItem[];
};

type PageIssue = { type: string; detail: string; affected_page: number };

type EcvDocument = {
  id: string;
  doc_number: number;
  name: string;
  mismo_type: string;
  pages: string;
  page_count: number;
  confidence: number;
  status: "found" | "missing";
  category: string;
  page_issue: PageIssue | null;
};

type Summary = {
  overall_score: number;
  auto_approve_threshold: number;
  confidence_threshold: number;
  critical_threshold: number;
  total_items: number;
  passed_items: number;
  review_items: number;
  critical_items: number;
  documents_found: number;
  documents_missing: number;
};

type EcvDashboard = {
  packet: Packet;
  summary: Summary;
  sections: Section[];
  documents: EcvDocument[];
};

/* ----- semantic palette (only tokens not in chrome) ------------------- */

const SUCCESS = "#10B981";
const SUCCESS_BG = "#D1FAE5";
const SUCCESS_BORDER = "#A7F3D0";
const DESTRUCTIVE = "#DC2626";
const DESTRUCTIVE_BG = "#FEE2E2";
const DESTRUCTIVE_BORDER = "#FCA5A5";
const PURPLE = "#BD33A4";
const PURPLE_LIGHT = "#F5DEF0";

function scoreStatus(score: number): { label: string; color: string; bg: string } {
  if (score >= 90) return { label: "PASS", color: SUCCESS, bg: SUCCESS_BG };
  if (score >= 75) return { label: "REVIEW", color: chrome.amber, bg: chrome.amberBg };
  return { label: "CRITICAL", color: DESTRUCTIVE, bg: DESTRUCTIVE_BG };
}

function severity(confidence: number, critThresh: number, confThresh: number) {
  if (confidence < critThresh) return "critical" as const;
  if (confidence < confThresh) return "review" as const;
  return "pass" as const;
}

/* ----- page ----------------------------------------------------------- */

export default function EcvPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const searchParams = useSearchParams();
  const packetId = searchParams.get("packet");
  const router = useRouter();
  const { ready } = useRequireRole(["customer_admin", "customer_user"], `/${orgSlug}`);
  const { token } = useAuth();

  const [data, setData] = useState<EcvDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token || !packetId) return;
    let cancelled = false;
    (async () => {
      try {
        const payload = await api<EcvDashboard>(`/api/packets/${packetId}/ecv`, { token });
        if (!cancelled) setData(payload);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 409) {
          setError("ECV is still processing this packet. Check back in a moment.");
        } else if (err instanceof ApiError) {
          setError(err.detail ?? `Couldn't load ECV results (${err.status}).`);
        } else {
          setError("Couldn't load ECV results.");
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
        <h1 style={titleStyle}>ECV Dashboard</h1>
        <p style={emptyStyle}>Nothing to show yet. Upload a packet to see ECV results.</p>
        <Link href={`/${orgSlug}/upload`} style={linkBtnStyle}>
          Upload a packet
        </Link>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: 800 }}>
        <h1 style={titleStyle}>ECV Dashboard</h1>
        <div role="alert" style={errorBoxStyle}>
          {error}
        </div>
        <div style={{ marginTop: 16 }}>
          <Link href={`/${orgSlug}/upload`} style={linkBtnStyle}>
            Upload another packet
          </Link>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ maxWidth: 800 }}>
        <h1 style={titleStyle}>ECV Dashboard</h1>
        <p style={emptyStyle}>Loading…</p>
      </div>
    );
  }

  return <Dashboard data={data} onReupload={() => router.push(`/${orgSlug}/upload`)} />;
}

/* ----- dashboard body ------------------------------------------------- */

function Dashboard({
  data,
  onReupload,
}: {
  data: EcvDashboard;
  onReupload: () => void;
}) {
  const { packet, summary, sections, documents } = data;
  const [tab, setTab] = useState<"documents" | "sections" | "review">("documents");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [collapsedCategories, setCollapsedCategories] = useState<Record<string, boolean>>({});
  const [reviewFilter, setReviewFilter] = useState<"all" | "critical" | "review">("all");

  const program = LOAN_PROGRAMS[packet.declared_program_id];

  const { itemsToReview, criticalItems, reviewItems } = useMemo(() => {
    const flat = sections.flatMap((sec) =>
      sec.line_items.map((it) => ({ ...it, sectionName: sec.name, sectionId: sec.section_number })),
    );
    const crit = flat.filter(
      (i) => severity(i.confidence, summary.critical_threshold, summary.confidence_threshold) === "critical",
    );
    const rev = flat.filter(
      (i) => severity(i.confidence, summary.critical_threshold, summary.confidence_threshold) === "review",
    );
    return { itemsToReview: [...crit, ...rev], criticalItems: crit, reviewItems: rev };
  }, [sections, summary.critical_threshold, summary.confidence_threshold]);

  const filteredReview = useMemo(() => {
    if (reviewFilter === "critical") return criticalItems;
    if (reviewFilter === "review") return reviewItems;
    return itemsToReview;
  }, [reviewFilter, itemsToReview, criticalItems, reviewItems]);

  const CATEGORY_ORDER = [
    "Application",
    "Credit",
    "Income",
    "Assets",
    "Employment",
    "Property",
    "Title",
    "Disclosure",
    "Insurance",
    "Closing",
  ];
  const docsByCategory: Record<string, EcvDocument[]> = {};
  documents.forEach((d) => {
    (docsByCategory[d.category] ??= []).push(d);
  });

  const overall = summary.overall_score;
  const stat = scoreStatus(overall);
  const shortId = packet.id.slice(0, 8);
  const uploaded = new Date(packet.created_at).toLocaleString();

  const toggleCategory = (cat: string) =>
    setCollapsedCategories((prev) => ({ ...prev, [cat]: !prev[cat] }));

  return (
    <div style={{ paddingBottom: 100 }}>
      {/* Hero */}
      <section style={{ ...cardStyle, padding: 0, marginBottom: 20, overflow: "hidden", position: "relative" }}>
        <div
          style={{
            position: "absolute",
            top: 0,
            right: 0,
            width: 300,
            height: 200,
            background: `radial-gradient(circle at top right, ${chrome.amber}10, transparent 70%)`,
            pointerEvents: "none",
          }}
        />
        <div
          style={{
            padding: "24px 28px",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 24,
            flexWrap: "wrap",
            position: "relative",
          }}
        >
          <div style={{ flex: 1, minWidth: 280 }}>
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: chrome.amber,
                letterSpacing: 1.2,
                textTransform: "uppercase",
                marginBottom: 6,
              }}
            >
              ECV Validation Report
            </div>
            <h1
              style={{
                fontSize: 24,
                fontWeight: 700,
                margin: "0 0 12px",
                color: chrome.charcoal,
                lineHeight: 1.2,
                fontFamily: typography.fontFamily.primary,
              }}
            >
              Packet {shortId}
            </h1>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13 }}>
              <HeroField label="Program" value={program?.label ?? packet.declared_program_id} />
              <HeroField label="Status" value={packet.status} pill />
              <HeroField label="Uploaded" value={uploaded} />
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 18, flexShrink: 0 }}>
            <Gauge score={overall} />
            <div>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: 1.2,
                  textTransform: "uppercase",
                  color: stat.color,
                  marginBottom: 4,
                }}
              >
                {stat.label === "REVIEW" ? "REVIEW REQUIRED" : stat.label}
              </div>
              <div style={{ fontSize: 13, color: chrome.charcoal, fontWeight: 500, lineHeight: 1.5, maxWidth: 200 }}>
                {overall >= summary.auto_approve_threshold
                  ? "Auto-approval eligible"
                  : `Score below ${summary.auto_approve_threshold}% — needs manual review`}
              </div>
              <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 4 }}>
                Weighted across {sections.length} sections
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* KPIs */}
      <section style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 20 }}>
        <KpiCard
          icon={<DocIcon size={18} color={chrome.amber} />}
          iconBg={chrome.amberBg}
          iconBorder={chrome.amberLight}
          label="Documents"
          value={`${summary.documents_found}/${summary.documents_found + summary.documents_missing}`}
          trend={{
            text: summary.documents_missing > 0 ? `${summary.documents_missing} missing` : "All present",
            color: summary.documents_missing > 0 ? DESTRUCTIVE : SUCCESS,
          }}
        />
        <KpiCard
          icon={<AlertIcon size={18} color={DESTRUCTIVE} />}
          iconBg={DESTRUCTIVE_BG}
          iconBorder={DESTRUCTIVE_BORDER}
          label="Items to review"
          value={String(itemsToReview.length)}
          trend={{
            text: `${summary.critical_items} critical · ${summary.review_items} amber`,
            color: DESTRUCTIVE,
          }}
        />
        <KpiCard
          icon={<CheckIcon size={18} color={SUCCESS} />}
          iconBg={SUCCESS_BG}
          iconBorder={SUCCESS_BORDER}
          label="Auto-verified"
          value={`${summary.passed_items}/${summary.total_items}`}
          trend={{
            text: `${itemsToReview.length} need review`,
            color: chrome.mutedFg,
          }}
        />
      </section>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 0, borderBottom: `2px solid ${chrome.border}`, marginBottom: 20 }}>
        {(
          [
            {
              key: "documents" as const,
              label: "Documents",
              count: documents.length,
              countColor: summary.documents_missing > 0 ? DESTRUCTIVE : SUCCESS,
            },
            { key: "sections" as const, label: "Section scores", count: sections.length, countColor: chrome.mutedFg },
            { key: "review" as const, label: "Items to review", count: itemsToReview.length, countColor: DESTRUCTIVE },
          ]
        ).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: "12px 20px",
              fontSize: 13,
              fontWeight: tab === t.key ? 600 : 500,
              border: "none",
              background: "none",
              cursor: "pointer",
              color: tab === t.key ? chrome.amber : chrome.mutedFg,
              borderBottom: tab === t.key ? `2px solid ${chrome.amber}` : "2px solid transparent",
              marginBottom: -2,
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontFamily: typography.fontFamily.primary,
            }}
          >
            {t.label}
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                color: tab === t.key ? "#fff" : t.countColor,
                background: tab === t.key ? chrome.amber : chrome.muted,
                padding: "2px 7px",
                borderRadius: 10,
                minWidth: 18,
                textAlign: "center",
              }}
            >
              {t.count}
            </span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "documents" && (
        <DocumentsTab
          docsByCategory={docsByCategory}
          categoryOrder={CATEGORY_ORDER}
          collapsed={collapsedCategories}
          toggle={toggleCategory}
          foundCount={summary.documents_found}
          missingCount={summary.documents_missing}
        />
      )}
      {tab === "sections" && (
        <SectionsTab sections={sections} expanded={expanded} setExpanded={setExpanded} />
      )}
      {tab === "review" && (
        <ReviewTab
          items={filteredReview}
          totalItems={summary.total_items}
          totalReview={itemsToReview.length}
          confidenceThreshold={summary.confidence_threshold}
          criticalThreshold={summary.critical_threshold}
          criticalCount={summary.critical_items}
          reviewCount={summary.review_items}
          filter={reviewFilter}
          setFilter={setReviewFilter}
        />
      )}

      {/* Sticky action bar */}
      <div
        style={{
          position: "fixed",
          bottom: 0,
          left: 240, // sidebar width
          right: 0,
          background: chrome.card,
          borderTop: `1px solid ${chrome.border}`,
          boxShadow: "0 -4px 16px rgba(20,18,14,0.04)",
          padding: "14px 28px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          zIndex: 10,
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <InfoIcon size={14} color={chrome.amber} />
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: chrome.charcoal }}>
              {overall >= summary.auto_approve_threshold ? "Auto-approval eligible" : "Manual review required"}
            </div>
            <div style={{ fontSize: 11, color: chrome.mutedFg }}>
              Current score <strong style={{ color: chrome.charcoal }}>{overall}%</strong>{" "}
              {overall >= summary.auto_approve_threshold ? "meets" : "is below"} the{" "}
              <strong>{summary.auto_approve_threshold}%</strong> auto-approval threshold
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            disabled={overall < summary.auto_approve_threshold}
            style={{ ...secondaryBtnStyle, opacity: overall < summary.auto_approve_threshold ? 0.4 : 1 }}
          >
            Approve packet
          </button>
          <button
            style={{
              padding: "10px 18px",
              fontSize: 13,
              fontWeight: 600,
              borderRadius: 8,
              border: `1px solid ${DESTRUCTIVE}40`,
              background: "#fff",
              color: DESTRUCTIVE,
              cursor: "pointer",
              fontFamily: typography.fontFamily.primary,
            }}
          >
            Reject
          </button>
          <div style={{ width: 1, height: 28, background: chrome.border, margin: "0 4px" }} />
          <button style={secondaryBtnStyle}>Export PDF</button>
          <button onClick={onReupload} style={ctaBtnStyle}>
            Upload new packet →
          </button>
        </div>
      </div>
    </div>
  );
}

/* ----- documents tab -------------------------------------------------- */

function DocumentsTab({
  docsByCategory,
  categoryOrder,
  collapsed,
  toggle,
  foundCount,
  missingCount,
}: {
  docsByCategory: Record<string, EcvDocument[]>;
  categoryOrder: string[];
  collapsed: Record<string, boolean>;
  toggle: (cat: string) => void;
  foundCount: number;
  missingCount: number;
}) {
  return (
    <div style={cardStyle}>
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${chrome.muted}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: chrome.charcoal }}>Document inventory</div>
        <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 2 }}>
          <span style={{ color: SUCCESS, fontWeight: 600 }}>{foundCount} found</span> ·{" "}
          <span style={{ color: missingCount > 0 ? DESTRUCTIVE : chrome.mutedFg, fontWeight: 600 }}>
            {missingCount} missing
          </span>{" "}
          · {categoryOrder.filter((c) => docsByCategory[c]).length} categories
        </div>
      </div>
      {categoryOrder.map((cat) => {
        const docs = docsByCategory[cat];
        if (!docs || docs.length === 0) return null;
        const isCollapsed = collapsed[cat];
        const catMissing = docs.filter((d) => d.status === "missing").length;
        return (
          <div key={cat}>
            <div
              onClick={() => toggle(cat)}
              style={{
                padding: "9px 20px",
                background: chrome.bg,
                borderBottom: `1px solid ${chrome.muted}`,
                display: "flex",
                alignItems: "center",
                gap: 10,
                cursor: "pointer",
              }}
            >
              <ChevronIcon open={!isCollapsed} color={chrome.mutedFg} />
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  color: chrome.mutedFg,
                  letterSpacing: 0.8,
                  textTransform: "uppercase",
                }}
              >
                {cat}
              </span>
              <span style={{ fontSize: 10, color: chrome.mutedFg }}>
                {docs.length} doc{docs.length > 1 ? "s" : ""}
              </span>
              {catMissing > 0 && (
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 700,
                    color: DESTRUCTIVE,
                    background: DESTRUCTIVE_BG,
                    border: `1px solid ${DESTRUCTIVE}30`,
                    padding: "1px 6px",
                    borderRadius: 3,
                    marginLeft: "auto",
                  }}
                >
                  {catMissing} missing
                </span>
              )}
            </div>
            {!isCollapsed &&
              docs.map((doc) => <DocumentRow key={doc.id} doc={doc} />)}
          </div>
        );
      })}
    </div>
  );
}

function DocumentRow({ doc }: { doc: EcvDocument }) {
  const isMissing = doc.status === "missing";
  const isHighConf = !isMissing && doc.confidence >= 95;
  return (
    <div
      style={{
        background: isMissing ? DESTRUCTIVE_BG + "60" : "transparent",
        borderLeft: isMissing ? `3px solid ${DESTRUCTIVE}` : "3px solid transparent",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "12px 20px",
          borderBottom: doc.page_issue ? "none" : `1px solid ${chrome.bg}`,
        }}
      >
        <div
          style={{
            width: 24,
            height: 24,
            borderRadius: 6,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: isMissing ? DESTRUCTIVE_BG : SUCCESS_BG,
            flexShrink: 0,
          }}
        >
          {isMissing ? <XIcon size={14} color={DESTRUCTIVE} /> : <CheckIcon size={12} color={SUCCESS} />}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: isMissing ? DESTRUCTIVE : chrome.charcoal,
              marginBottom: 3,
            }}
          >
            {doc.name}
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <span
              style={{
                fontSize: 9,
                fontFamily: "monospace",
                fontWeight: 600,
                color: PURPLE,
                background: PURPLE_LIGHT,
                border: `1px solid ${PURPLE}20`,
                padding: "1px 6px",
                borderRadius: 3,
              }}
            >
              {doc.mismo_type}
            </span>
            {!isMissing && (
              <span
                style={{
                  fontSize: 10,
                  color: chrome.mutedFg,
                  background: chrome.muted,
                  padding: "1px 6px",
                  borderRadius: 3,
                }}
              >
                p. {doc.pages}
              </span>
            )}
          </div>
        </div>
        <div style={{ textAlign: "right", minWidth: 100, flexShrink: 0 }}>
          {isMissing ? (
            <span
              style={{
                fontSize: 9,
                fontWeight: 700,
                color: DESTRUCTIVE,
                background: "#fff",
                border: `1px solid ${DESTRUCTIVE}40`,
                padding: "3px 10px",
                borderRadius: 4,
                letterSpacing: 0.5,
              }}
            >
              MISSING
            </span>
          ) : isHighConf ? (
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: SUCCESS,
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <CheckIcon size={12} color={SUCCESS} /> Verified
            </span>
          ) : (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background:
                    doc.confidence >= 90 ? SUCCESS : doc.confidence >= 75 ? chrome.amber : DESTRUCTIVE,
                }}
              />
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: doc.confidence >= 90 ? SUCCESS : doc.confidence >= 75 ? chrome.amber : DESTRUCTIVE,
                }}
              >
                {doc.confidence}%
              </span>
            </span>
          )}
        </div>
      </div>
      {doc.page_issue && (
        <div
          style={{
            padding: "6px 20px 10px 56px",
            background: chrome.amberBg,
            borderBottom: `1px solid ${chrome.amberLight}`,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <AlertIcon size={12} color={chrome.amber} />
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              color: "#92400E",
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            {doc.page_issue.type === "blank_page"
              ? "BLANK PAGE"
              : doc.page_issue.type === "low_quality"
                ? "LOW QUALITY"
                : "ROTATED"}
          </span>
          <span style={{ fontSize: 10, color: "#78350F" }}>{doc.page_issue.detail}</span>
        </div>
      )}
    </div>
  );
}

/* ----- sections tab --------------------------------------------------- */

function SectionsTab({
  sections,
  expanded,
  setExpanded,
}: {
  sections: Section[];
  expanded: number | null;
  setExpanded: (n: number | null) => void;
}) {
  return (
    <div style={cardStyle}>
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${chrome.muted}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: chrome.charcoal }}>
          Section scores
        </div>
        <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 2 }}>
          {sections.length} validation sections weighted into the overall score.
        </div>
      </div>
      {sections.map((sec) => {
        const isOpen = expanded === sec.section_number;
        const stat = scoreStatus(sec.score);
        return (
          <div key={sec.id} style={{ borderBottom: `1px solid ${chrome.bg}` }}>
            <div
              onClick={() => setExpanded(isOpen ? null : sec.section_number)}
              style={{
                padding: "14px 20px",
                display: "flex",
                alignItems: "center",
                gap: 14,
                cursor: "pointer",
              }}
            >
              <ChevronIcon open={isOpen} color={chrome.mutedFg} />
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  color: chrome.mutedFg,
                  fontFamily: "monospace",
                  width: 24,
                }}
              >
                {String(sec.section_number).padStart(2, "0")}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: chrome.charcoal }}>
                  {sec.name}
                </div>
                <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 2 }}>
                  {sec.line_items.length} check{sec.line_items.length === 1 ? "" : "s"} · weight{" "}
                  {(sec.weight * 100).toFixed(0)}%
                </div>
              </div>
              <div style={{ width: 160, flexShrink: 0 }}>
                <Bar value={sec.score} color={stat.color} />
              </div>
              <div style={{ width: 90, textAlign: "right", flexShrink: 0 }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: stat.color }}>
                  {sec.score.toFixed(0)}%
                </div>
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 700,
                    color: stat.color,
                    background: stat.bg,
                    padding: "1px 6px",
                    borderRadius: 3,
                    letterSpacing: 0.4,
                  }}
                >
                  {stat.label}
                </span>
              </div>
            </div>
            {isOpen && (
              <div style={{ background: chrome.bg, padding: "4px 20px 14px 58px" }}>
                {sec.line_items.map((it) => {
                  const dot =
                    it.confidence >= 90 ? SUCCESS : it.confidence >= 75 ? chrome.amber : DESTRUCTIVE;
                  return (
                    <div
                      key={it.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "8px 0",
                        borderBottom: `1px solid ${chrome.muted}`,
                      }}
                    >
                      <span
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: dot,
                          flexShrink: 0,
                        }}
                      />
                      <span
                        style={{
                          fontSize: 10,
                          fontFamily: "monospace",
                          color: chrome.mutedFg,
                          width: 70,
                        }}
                      >
                        {it.item_code}
                      </span>
                      <span style={{ fontSize: 12, color: chrome.charcoal, flex: 1 }}>
                        {it.check}
                      </span>
                      <span style={{ fontSize: 11, color: chrome.mutedFg, maxWidth: 220, textAlign: "right" }}>
                        {it.result}
                      </span>
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 700,
                          color: dot,
                          width: 48,
                          textAlign: "right",
                        }}
                      >
                        {it.confidence}%
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Bar({ value, color }: { value: number; color: string }) {
  return (
    <div
      style={{
        height: 6,
        background: chrome.muted,
        borderRadius: 3,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: `${Math.max(0, Math.min(100, value))}%`,
          height: "100%",
          background: color,
          transition: "width 200ms ease",
        }}
      />
    </div>
  );
}

/* ----- review tab ----------------------------------------------------- */

type ReviewItem = LineItem & { sectionName: string; sectionId: number };

function ReviewTab({
  items,
  totalItems,
  totalReview,
  confidenceThreshold,
  criticalThreshold,
  criticalCount,
  reviewCount,
  filter,
  setFilter,
}: {
  items: ReviewItem[];
  totalItems: number;
  totalReview: number;
  confidenceThreshold: number;
  criticalThreshold: number;
  criticalCount: number;
  reviewCount: number;
  filter: "all" | "critical" | "review";
  setFilter: (f: "all" | "critical" | "review") => void;
}) {
  const sorted = useMemo(
    () => [...items].sort((a, b) => a.confidence - b.confidence),
    [items],
  );

  return (
    <div style={cardStyle}>
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${chrome.muted}` }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: chrome.charcoal }}>
          Items to review
        </div>
        <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 2 }}>
          {totalReview} of {totalItems} line items fell below the {confidenceThreshold}% confidence
          threshold · critical &lt; {criticalThreshold}%.
        </div>
      </div>
      <div
        style={{
          padding: "10px 20px",
          borderBottom: `1px solid ${chrome.muted}`,
          display: "flex",
          gap: 8,
        }}
      >
        {(
          [
            { key: "all" as const, label: `All (${totalReview})`, color: chrome.charcoal },
            { key: "critical" as const, label: `Critical (${criticalCount})`, color: DESTRUCTIVE },
            { key: "review" as const, label: `Review (${reviewCount})`, color: chrome.amber },
          ]
        ).map((f) => {
          const active = filter === f.key;
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              style={{
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: 0.4,
                textTransform: "uppercase",
                padding: "6px 12px",
                borderRadius: 14,
                cursor: "pointer",
                border: `1px solid ${active ? f.color : chrome.border}`,
                background: active ? f.color : "#fff",
                color: active ? "#fff" : f.color,
                fontFamily: typography.fontFamily.primary,
              }}
            >
              {f.label}
            </button>
          );
        })}
      </div>
      {sorted.length === 0 ? (
        <div style={{ padding: "40px 20px", textAlign: "center" }}>
          <div style={{ fontSize: 32, marginBottom: 6 }}>
            <CheckIcon size={32} color={SUCCESS} />
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: chrome.charcoal }}>
            Nothing to review in this filter.
          </div>
          <div style={{ fontSize: 12, color: chrome.mutedFg, marginTop: 4 }}>
            Items that fall below the confidence threshold will surface here.
          </div>
        </div>
      ) : (
        sorted.map((it) => {
          const sev =
            it.confidence < criticalThreshold
              ? { label: "CRITICAL", color: DESTRUCTIVE, bg: DESTRUCTIVE_BG }
              : { label: "REVIEW", color: chrome.amber, bg: chrome.amberBg };
          return (
            <div
              key={it.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 14,
                padding: "12px 20px",
                borderBottom: `1px solid ${chrome.bg}`,
                borderLeft: `3px solid ${sev.color}`,
              }}
            >
              <span
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  color: sev.color,
                  background: sev.bg,
                  padding: "2px 8px",
                  borderRadius: 3,
                  letterSpacing: 0.5,
                  flexShrink: 0,
                }}
              >
                {sev.label}
              </span>
              <span
                style={{
                  fontSize: 10,
                  fontFamily: "monospace",
                  color: chrome.mutedFg,
                  width: 70,
                  flexShrink: 0,
                }}
              >
                {it.item_code}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: chrome.charcoal }}>
                  {it.check}
                </div>
                <div style={{ fontSize: 11, color: chrome.mutedFg, marginTop: 2 }}>
                  §{it.sectionId} {it.sectionName} · {it.result}
                </div>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: sev.color }}>
                  {it.confidence}%
                </div>
                <div style={{ fontSize: 10, color: chrome.mutedFg }}>confidence</div>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

/* ----- small helpers -------------------------------------------------- */

function HeroField({ label, value, pill }: { label: string; value: string; pill?: boolean }) {
  return (
    <div>
      <div
        style={{
          fontSize: 9,
          fontWeight: 700,
          color: chrome.mutedFg,
          letterSpacing: 0.8,
          textTransform: "uppercase",
          marginBottom: 3,
        }}
      >
        {label}
      </div>
      {pill ? (
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: chrome.amber,
            background: chrome.amberBg,
            border: `1px solid ${chrome.amberLight}`,
            padding: "2px 8px",
            borderRadius: 10,
            textTransform: "capitalize",
            letterSpacing: 0.3,
          }}
        >
          {value.replace(/_/g, " ")}
        </span>
      ) : (
        <div style={{ fontSize: 13, fontWeight: 600, color: chrome.charcoal }}>{value}</div>
      )}
    </div>
  );
}

function KpiCard({
  icon,
  iconBg,
  iconBorder,
  label,
  value,
  trend,
}: {
  icon: React.ReactNode;
  iconBg: string;
  iconBorder: string;
  label: string;
  value: string;
  trend: { text: string; color: string };
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        ...cardStyle,
        padding: 18,
        transform: hover ? "translateY(-2px)" : "translateY(0)",
        boxShadow: hover ? "0 4px 16px rgba(20,18,14,0.08)" : "0 1px 2px rgba(20,18,14,0.03)",
        transition: "transform 180ms ease, box-shadow 180ms ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 9,
            background: iconBg,
            border: `1px solid ${iconBorder}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: chrome.mutedFg,
            letterSpacing: 0.8,
            textTransform: "uppercase",
          }}
        >
          {label}
        </div>
      </div>
      <div
        style={{
          fontSize: 28,
          fontWeight: 700,
          color: chrome.charcoal,
          lineHeight: 1,
          marginBottom: 6,
          fontFamily: typography.fontFamily.primary,
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 11, color: trend.color, fontWeight: 500 }}>{trend.text}</div>
    </div>
  );
}

function Gauge({ score }: { score: number }) {
  const stat = scoreStatus(score);
  const size = 120;
  const stroke = 10;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, score));
  const offset = circumference - (clamped / 100) * circumference;
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={chrome.muted}
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={stat.color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 300ms ease" }}
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            fontSize: 26,
            fontWeight: 700,
            color: chrome.charcoal,
            lineHeight: 1,
            fontFamily: typography.fontFamily.primary,
          }}
        >
          {score.toFixed(0)}
        </div>
        <div
          style={{
            fontSize: 9,
            fontWeight: 700,
            color: chrome.mutedFg,
            letterSpacing: 0.6,
            textTransform: "uppercase",
            marginTop: 2,
          }}
        >
          Score
        </div>
      </div>
    </div>
  );
}

/* ----- icons (inline SVG per CLAUDE.md) ------------------------------- */

function DocIcon({ size = 16, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="13" y2="17" />
    </svg>
  );
}

function AlertIcon({ size = 16, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <circle cx="12" cy="17" r="0.6" fill={color} />
    </svg>
  );
}

function CheckIcon({ size = 16, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function XIcon({ size = 16, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function InfoIcon({ size = 16, color = "currentColor" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <circle cx="12" cy="8" r="0.6" fill={color} />
    </svg>
  );
}

function ChevronIcon({ open, color = "currentColor" }: { open: boolean; color?: string }) {
  return (
    <svg
      width={12}
      height={12}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        transform: open ? "rotate(90deg)" : "rotate(0deg)",
        transition: "transform 150ms ease",
      }}
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

/* ----- shared style constants ---------------------------------------- */

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
  margin: "8px 0 16px",
};

const errorBoxStyle: React.CSSProperties = {
  padding: "12px 16px",
  borderRadius: 8,
  background: DESTRUCTIVE_BG,
  border: `1px solid ${DESTRUCTIVE_BORDER}`,
  color: DESTRUCTIVE,
  fontSize: 13,
  fontWeight: 500,
};

const linkBtnStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "9px 16px",
  fontSize: 13,
  fontWeight: 600,
  color: "#fff",
  background: chrome.amber,
  borderRadius: 8,
  textDecoration: "none",
  fontFamily: typography.fontFamily.primary,
};

const secondaryBtnStyle: React.CSSProperties = {
  padding: "10px 18px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: 8,
  border: `1px solid ${chrome.border}`,
  background: "#fff",
  color: chrome.charcoal,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const ctaBtnStyle: React.CSSProperties = {
  padding: "10px 18px",
  fontSize: 13,
  fontWeight: 700,
  borderRadius: 8,
  border: "none",
  background: chrome.amber,
  color: "#fff",
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};
