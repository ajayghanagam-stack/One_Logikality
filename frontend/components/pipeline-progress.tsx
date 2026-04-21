"use client";

/**
 * Multi-stage pipeline animation (US-3.4).
 *
 * Polls `GET /api/packets/{id}` every 400ms and syncs the stepper to
 * the server's `current_stage` + `status`. When `status` transitions
 * to `completed`, we leave the "ready" state up briefly so the user
 * registers the finish, then call `onComplete()` — the upload page
 * uses that to route on to the ECV dashboard.
 *
 * Visual language matches the `one-logikality-demo` pipeline component
 * (same six stages, same human-language labels, same amber/green palette)
 * so ECV-in-production reads as the same family as the reference. Uses
 * the approved Logikality logo per CLAUDE.md; never inlined as SVG.
 */

import Image from "next/image";
import { useEffect, useRef, useState } from "react";

import { chrome, logo, typography } from "@/lib/brand";

// Stage ids mirror `backend/app/pipeline/ecv_stub.py::PIPELINE_STAGES`
// exactly. The human labels come from the demo so the two products
// read identically during the demo-to-prod transition.
const PIPELINE_STAGES: readonly { id: string; label: string }[] = [
  { id: "ingest", label: "Reading pages" },
  { id: "classify", label: "Identifying documents" },
  { id: "extract", label: "Extracting data" },
  { id: "validate", label: "Checking consistency" },
  { id: "score", label: "Scoring confidence" },
  { id: "route", label: "Preparing dashboard" },
] as const;

// Demo parity — emerald-500. Not promoted to `chrome` yet because this
// is the only surface using it; lift it the second time we need it.
const SUCCESS = "#10B981";

type PacketView = {
  id: string;
  status: string;
  current_stage: string | null;
};

export function PipelineProgress({
  packetId,
  token,
  onComplete,
}: {
  packetId: string;
  token: string;
  onComplete: () => void;
}) {
  // -1 means "not yet started" — the packet row has status='uploaded'
  // and current_stage=NULL. The stepper renders the first node as
  // upcoming in that state, so the UI never flashes an empty card.
  const [stageIndex, setStageIndex] = useState(-1);
  const [isComplete, setIsComplete] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const doneTriggered = useRef(false);

  useEffect(() => {
    if (isComplete) return;
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch(`/api/packets/${packetId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`status ${res.status}`);
        const data: PacketView = await res.json();
        if (cancelled) return;

        if (data.status === "failed") {
          setErrorMessage(
            "Processing failed. Please retry the upload or contact support.",
          );
          return;
        }

        const idx = data.current_stage
          ? PIPELINE_STAGES.findIndex((s) => s.id === data.current_stage)
          : -1;
        setStageIndex(idx);

        if (data.status === "completed" && !doneTriggered.current) {
          doneTriggered.current = true;
          setIsComplete(true);
          // Short dwell so the "ready" frame is actually visible —
          // the upload-to-dashboard hand-off would otherwise look
          // like a flicker on a fast stub run.
          setTimeout(onComplete, 900);
        }
      } catch {
        // Transient network failure — stay on the current frame, keep
        // polling. A real outage will show up as the poll never
        // advancing, which the user can bail out of.
        if (!cancelled) setErrorMessage("Reconnecting to the server…");
      }
    }

    // First poll fires immediately so the UI doesn't sit on "not
    // started" for a full interval when the stub has already begun.
    poll();
    const timer = setInterval(poll, 400);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [packetId, token, onComplete, isComplete]);

  // Progress bar snaps to stage boundaries — the server only emits
  // discrete stage transitions, not intra-stage progress, so smoothing
  // here would be a lie. At ~0.8s per stage (prod default) the jumps
  // feel purposeful rather than jittery.
  const overallProgress = isComplete
    ? 100
    : stageIndex < 0
      ? 3
      : ((stageIndex + 1) / PIPELINE_STAGES.length) * 100;

  const activeStage = PIPELINE_STAGES[Math.max(0, stageIndex)];
  const topLabel = isComplete
    ? "Complete"
    : errorMessage
      ? "Reconnecting"
      : stageIndex < 0
        ? "Starting"
        : activeStage.label;

  return (
    <div style={overlayStyle}>
      <div style={ambientStyle} />

      <div style={contentStyle}>
        {/* Logo — approved PNG per CLAUDE.md; never inline-SVG the mark. */}
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            marginBottom: 48,
          }}
        >
          <Image
            src={logo.withTaglinePng}
            alt="Logikality"
            width={160}
            height={44}
            priority
            style={{ height: "auto", maxWidth: 160 }}
          />
        </div>

        <div style={{ textAlign: "center", marginBottom: 40 }}>
          <h1 style={titleStyle}>
            {isComplete ? "Your packet is ready" : "Processing your packet"}
          </h1>
          <p style={subtitleStyle}>
            {isComplete
              ? "Opening your dashboard…"
              : "This typically takes under 5 seconds."}
          </p>
          {errorMessage ? <p style={errorStyle}>{errorMessage}</p> : null}
        </div>

        <div style={cardStyle}>
          {/* Overall progress bar */}
          <div style={{ marginBottom: 32 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                marginBottom: 8,
              }}
            >
              <span style={progressLabelStyle}>{topLabel}</span>
              <span style={progressPctStyle}>
                {isComplete ? "100%" : `${Math.round(overallProgress)}%`}
              </span>
            </div>
            <div style={progressTrackStyle}>
              <div
                style={{
                  ...progressFillStyle,
                  width: `${overallProgress}%`,
                }}
              />
            </div>
          </div>

          {/* Stepper */}
          <div style={stepperStyle}>
            {PIPELINE_STAGES.map((stage, i) => {
              const done = i < stageIndex || isComplete;
              const active = i === stageIndex && !isComplete;
              const nodeBg = done
                ? SUCCESS
                : active
                  ? chrome.amber
                  : chrome.muted;
              const nodeFg = done || active ? "#fff" : chrome.mutedFg;

              return (
                <div key={stage.id} style={nodeColumnStyle}>
                  {i < PIPELINE_STAGES.length - 1 ? (
                    <div
                      style={{
                        ...connectorStyle,
                        background: done
                          ? SUCCESS
                          : active
                            ? chrome.amber
                            : chrome.border,
                      }}
                    />
                  ) : null}

                  <div
                    style={{
                      ...nodeStyle,
                      background: nodeBg,
                      color: nodeFg,
                      boxShadow: active
                        ? `0 0 0 3px ${chrome.amber}30, 0 0 20px ${chrome.amber}40`
                        : done
                          ? `0 0 0 2px ${SUCCESS}20`
                          : "none",
                    }}
                  >
                    {done ? (
                      <CheckIcon />
                    ) : (
                      <StageIcon id={stage.id} index={i} />
                    )}
                  </div>

                  <div
                    style={{
                      ...labelStyle,
                      color: done
                        ? SUCCESS
                        : active
                          ? chrome.amber
                          : chrome.mutedFg,
                    }}
                  >
                    {stage.label}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ----- icons --------------------------------------------------------- */

function CheckIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function StageIcon({ id, index }: { id: string; index: number }) {
  switch (id) {
    case "ingest":
      return (
        <svg {...svgProps}>
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      );
    case "classify":
      return (
        <svg {...svgProps}>
          <rect x="3" y="3" width="7" height="7" />
          <rect x="14" y="3" width="7" height="7" />
          <rect x="14" y="14" width="7" height="7" />
          <rect x="3" y="14" width="7" height="7" />
        </svg>
      );
    case "extract":
      return (
        <svg {...svgProps}>
          <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        </svg>
      );
    case "validate":
      return (
        <svg {...svgProps}>
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      );
    case "score":
      return (
        <svg {...svgProps}>
          <line x1="18" y1="20" x2="18" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="6" y1="20" x2="6" y2="14" />
        </svg>
      );
    case "route":
      return (
        <svg {...svgProps}>
          <path d="M5 12h14M12 5l7 7-7 7" />
        </svg>
      );
    default:
      return <span style={{ fontSize: 14, fontWeight: 700 }}>{index + 1}</span>;
  }
}

const svgProps = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

/* ----- styles -------------------------------------------------------- */

const overlayStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 100,
  background: `linear-gradient(135deg, ${chrome.bg} 0%, ${chrome.amberBg} 50%, ${chrome.bg} 100%)`,
  overflow: "auto",
};

const ambientStyle: React.CSSProperties = {
  position: "absolute",
  inset: 0,
  pointerEvents: "none",
  backgroundImage: `radial-gradient(circle at 20% 20%, ${chrome.amber}14 0%, transparent 40%), radial-gradient(circle at 80% 70%, ${chrome.amberDark}10 0%, transparent 40%)`,
};

const contentStyle: React.CSSProperties = {
  position: "relative",
  maxWidth: 860,
  margin: "0 auto",
  padding: "40px 32px",
};

const titleStyle: React.CSSProperties = {
  fontSize: 32,
  fontWeight: typography.fontWeight.headline,
  margin: "0 0 12px",
  color: chrome.charcoal,
  letterSpacing: "-0.02em",
  fontFamily: typography.fontFamily.primary,
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 15,
  color: chrome.mutedFg,
  margin: 0,
  maxWidth: 480,
  marginLeft: "auto",
  marginRight: "auto",
  lineHeight: 1.5,
};

const errorStyle: React.CSSProperties = {
  marginTop: 14,
  fontSize: 12,
  color: "#991B1B",
  background: "#FEE2E2",
  border: "1px solid #FCA5A5",
  display: "inline-block",
  padding: "6px 12px",
  borderRadius: 6,
};

const cardStyle: React.CSSProperties = {
  background: chrome.card,
  borderRadius: 16,
  border: `1px solid ${chrome.border}`,
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
  padding: "36px 40px",
};

const progressLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  color: chrome.mutedFg,
  letterSpacing: 1,
  textTransform: "uppercase",
};

const progressPctStyle: React.CSSProperties = {
  fontSize: 15,
  fontWeight: 800,
  color: chrome.amber,
  fontVariantNumeric: "tabular-nums",
  letterSpacing: "-0.02em",
};

const progressTrackStyle: React.CSSProperties = {
  height: 8,
  background: chrome.muted,
  borderRadius: 4,
  overflow: "hidden",
};

const progressFillStyle: React.CSSProperties = {
  height: "100%",
  background: `linear-gradient(90deg, ${chrome.amber}, ${chrome.amberDark})`,
  borderRadius: 4,
  transition: "width 0.3s ease",
};

const stepperStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  position: "relative",
};

const nodeColumnStyle: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  position: "relative",
};

const connectorStyle: React.CSSProperties = {
  position: "absolute",
  top: 26,
  left: "50%",
  width: "100%",
  height: 2,
  zIndex: 0,
};

const nodeStyle: React.CSSProperties = {
  width: 52,
  height: 52,
  borderRadius: "50%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  border: "3px solid #fff",
  zIndex: 1,
  transition: "all 0.3s ease",
  position: "relative",
};

const labelStyle: React.CSSProperties = {
  marginTop: 12,
  textAlign: "center",
  maxWidth: 120,
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: 0.3,
  textTransform: "uppercase",
  transition: "color 0.3s ease",
};
