"use client";

/**
 * Packet upload page (US-3.1 / US-3.2 / US-3.3 / US-3.4).
 *
 * Drag-drop + file picker for PDF/PNG/JPEG, a loan-program selector
 * that drives the right rule set, and a facts panel previewing which
 * values will apply. Layout and copy mirror the `one-logikality-demo`
 * reference so both products feel like one family.
 *
 * Submits multipart to `POST /api/packets`. On success the page hands
 * off to `<PipelineProgress>` which polls the packet's server state
 * until it reaches `completed`, then routes the user to the ECV
 * dashboard (US-3.4).
 */

import { useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { PipelineProgress } from "@/components/pipeline-progress";
import { ApiError } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";
import { LOAN_PROGRAMS } from "@/lib/rules";

type QueuedFile = { file: File; id: string };

type PacketCreatedResponse = {
  // The full PacketOut carries more — we only need the id to hand off
  // to `<PipelineProgress>`, which polls the packet itself.
  id: string;
};

const ACCEPT = ".pdf,.png,.jpg,.jpeg";
const ACCEPT_RE = /\.(pdf|png|jpg|jpeg)$/i;

export default function UploadPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const router = useRouter();
  const { ready } = useRequireRole(
    ["customer_admin", "customer_user"],
    `/${orgSlug}`,
  );
  const { user, token } = useAuth();

  const [queued, setQueued] = useState<QueuedFile[]>([]);
  const [programId, setProgramId] = useState<string>("conventional");
  const [dragActive, setDragActive] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // Non-null once `POST /api/packets` succeeds — drives the
  // full-screen `<PipelineProgress>` overlay which polls server state
  // and routes to the ECV dashboard on completion.
  const [processingPacketId, setProcessingPacketId] = useState<string | null>(
    null,
  );
  const [submitError, setSubmitError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  if (!ready) return null;

  const program = LOAN_PROGRAMS[programId];
  const totalBytes = queued.reduce((s, q) => s + q.file.size, 0);

  function addFiles(list: FileList | File[]) {
    const incoming = Array.from(list).filter((f) => ACCEPT_RE.test(f.name));
    if (incoming.length === 0) return;
    setQueued((prev) => [
      ...prev,
      ...incoming.map((file) => ({
        file,
        id: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`,
      })),
    ]);
  }

  function removeQueued(id: string) {
    setQueued((prev) => prev.filter((q) => q.id !== id));
  }

  async function handleAnalyze() {
    if (!token || queued.length === 0) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const body = new FormData();
      body.set("declared_program_id", programId);
      for (const q of queued) body.append("files", q.file, q.file.name);

      const res = await fetch("/api/packets", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body,
      });
      if (!res.ok) {
        let detail: string | undefined;
        try {
          detail = (await res.json())?.detail;
        } catch {
          // response wasn't JSON
        }
        throw new ApiError(
          res.status,
          detail,
          detail ?? `upload failed: ${res.status}`,
        );
      }
      const payload: PacketCreatedResponse = await res.json();
      setQueued([]);
      setProcessingPacketId(payload.id);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? (err.detail ?? `Upload failed (${err.status}).`)
          : "Upload failed. Please try again.";
      setSubmitError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 800 }}>
      {processingPacketId && token ? (
        <PipelineProgress
          packetId={processingPacketId}
          token={token}
          onComplete={() =>
            router.push(`/${orgSlug}/ecv?packet=${processingPacketId}`)
          }
        />
      ) : null}

      <h1 style={titleStyle}>Upload documents</h1>
      <p style={subtitleStyle}>
        {user?.full_name ? orgDisplay(user.full_name) : "Your organization"} ·
        Upload your mortgage document packet for ECV analysis
      </p>

      <Dropzone
        dragActive={dragActive}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          addFiles(e.dataTransfer.files);
        }}
      />
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        style={{ display: "none" }}
        onChange={(e) => {
          if (e.target.files) addFiles(e.target.files);
          e.target.value = "";
        }}
      />

      {queued.length > 0 ? (
        <FileList
          files={queued}
          totalBytes={totalBytes}
          onRemove={removeQueued}
        />
      ) : null}

      <ProgramPanel programId={programId} onChange={setProgramId} />

      {submitError ? (
        <div role="alert" style={errorStyle}>
          {submitError}
        </div>
      ) : null}

      <button
        type="button"
        onClick={handleAnalyze}
        disabled={queued.length === 0 || submitting}
        style={{
          ...analyzeBtnStyle,
          opacity: queued.length === 0 || submitting ? 0.5 : 1,
          cursor: queued.length === 0 || submitting ? "not-allowed" : "pointer",
        }}
      >
        {submitting ? "Uploading…" : `Analyze packet (${program.label})`}
      </button>
    </div>
  );
}

/* ----- subcomponents ------------------------------------------------- */

function Dropzone({
  dragActive,
  onClick,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  dragActive: boolean;
  onClick: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}) {
  return (
    <div
      onClick={onClick}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        borderRadius: 10,
        border: `2px dashed ${dragActive ? chrome.amber : chrome.border}`,
        padding: "40px 20px",
        textAlign: "center",
        cursor: "pointer",
        background: dragActive ? chrome.amberBg : chrome.bg,
        transition: "all 0.2s",
        transform: dragActive ? "scale(1.01)" : "scale(1)",
        marginBottom: 20,
      }}
    >
      <div style={uploadIconStyle}>
        <svg
          width="28"
          height="28"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#0EA5E9"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      </div>
      <p style={{ fontSize: 14, fontWeight: 600, margin: "0 0 6px" }}>
        Upload a Mortgage Document Packet
      </p>
      <p style={{ fontSize: 12, color: chrome.mutedFg, margin: "0 0 16px" }}>
        Supports PDF, PNG, and JPEG files. Upload all documents for a single
        package together.
      </p>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        style={selectFilesBtnStyle}
      >
        Select Files
      </button>
    </div>
  );
}

function FileList({
  files,
  totalBytes,
  onRemove,
}: {
  files: QueuedFile[];
  totalBytes: number;
  onRemove: (id: string) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        marginBottom: 20,
      }}
    >
      {files.map((q) => (
        <div key={q.id} style={fileRowStyle}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke={chrome.mutedFg}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            <span style={{ fontSize: 13, fontWeight: 500 }}>{q.file.name}</span>
            <span style={{ fontSize: 11, color: chrome.mutedFg }}>
              {(q.file.size / 1024 / 1024).toFixed(1)} MB
            </span>
          </div>
          <button
            type="button"
            onClick={() => onRemove(q.id)}
            style={removeBtnStyle}
            aria-label={`Remove ${q.file.name}`}
          >
            ×
          </button>
        </div>
      ))}
      <div style={{ fontSize: 11, color: chrome.mutedFg, textAlign: "right" }}>
        {files.length} file{files.length > 1 ? "s" : ""} ·{" "}
        {(totalBytes / 1024 / 1024).toFixed(1)} MB total
      </div>
    </div>
  );
}

function ProgramPanel({
  programId,
  onChange,
}: {
  programId: string;
  onChange: (id: string) => void;
}) {
  const p = LOAN_PROGRAMS[programId];
  const shortFramework =
    p.regulatoryFramework.length > 24
      ? p.regulatoryFramework.substring(0, 22) + "…"
      : p.regulatoryFramework;
  const shortGuidelines =
    p.guidelines.length > 26
      ? p.guidelines.substring(0, 24) + "…"
      : p.guidelines;
  const facts: { label: string; value: string; help?: string }[] = [
    {
      label: "DTI limit",
      value: `${p.dtiLimit}%`,
      help: "Maximum debt-to-income ratio",
    },
    {
      label: "Chain depth",
      value: `${p.chainDepth} yrs`,
      help: "Years of title history to search",
    },
    { label: "Framework", value: shortFramework, help: p.regulatoryFramework },
    { label: "Guidelines", value: shortGuidelines, help: p.guidelines },
  ];

  return (
    <div style={programCardStyle}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 10,
        }}
      >
        <div style={programIconStyle}>
          <svg
            width="13"
            height="13"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="2" y="7" width="20" height="14" rx="2" />
            <path d="M16 21V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v16" />
          </svg>
        </div>
        <div style={{ flex: 1 }}>
          <div
            style={{ fontSize: 13, fontWeight: 700, color: chrome.charcoal }}
          >
            Loan program
          </div>
          <div style={{ fontSize: 11, color: chrome.mutedFg }}>
            Declare the program for this packet. ECV will confirm against your
            documents.
          </div>
        </div>
      </div>

      <select
        value={programId}
        onChange={(e) => onChange(e.target.value)}
        style={programSelectStyle}
      >
        {Object.values(LOAN_PROGRAMS).map((prog) => (
          <option key={prog.id} value={prog.id}>
            {prog.label}
          </option>
        ))}
      </select>

      <div style={factsPanelStyle}>
        <div style={factsHeaderStyle}>Rules that will apply for {p.label}</div>
        <div style={factsGridStyle}>
          {facts.map((f) => (
            <div key={f.label} title={f.help} style={factCellStyle}>
              <span style={factLabelStyle}>{f.label}</span>
              <span style={factValueStyle}>{f.value}</span>
            </div>
          ))}
        </div>
        <div
          style={{
            fontSize: 11,
            color: chrome.amberDark,
            lineHeight: 1.5,
            fontStyle: "italic",
          }}
        >
          {p.description}
        </div>
        {p.residualIncome ? (
          <div style={residualPillStyle}>
            <span style={{ fontSize: 10 }}>✓</span>
            <span>
              <strong>Residual income</strong> calculation required
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* ----- helpers ------------------------------------------------------- */

function orgDisplay(fullName: string): string {
  // Falls back to first name if the sidebar org name isn't piped through
  // yet. Keeps parity with the demo's "Acme Mortgage Holdings · ..." copy
  // pattern without guessing the org name on the page.
  return fullName.includes(" ") ? "Your organization" : fullName;
}

/* ----- styles -------------------------------------------------------- */

const titleStyle: React.CSSProperties = {
  fontSize: 22,
  fontWeight: typography.fontWeight.headline,
  margin: "0 0 4px",
  color: chrome.charcoal,
  letterSpacing: "-0.02em",
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 13,
  color: chrome.mutedFg,
  margin: "0 0 24px",
};

const uploadIconStyle: React.CSSProperties = {
  width: 56,
  height: 56,
  borderRadius: "50%",
  background: "#E0F2FE",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  margin: "0 auto 12px",
};

const selectFilesBtnStyle: React.CSSProperties = {
  padding: "9px 18px",
  fontSize: 13,
  fontWeight: 600,
  background: chrome.amber,
  color: "#fff",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const fileRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "10px 14px",
  borderRadius: 8,
  background: chrome.muted,
};

const removeBtnStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  cursor: "pointer",
  color: chrome.mutedFg,
  fontSize: 18,
  lineHeight: 1,
  padding: 0,
  fontFamily: typography.fontFamily.primary,
};

const programCardStyle: React.CSSProperties = {
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 10,
  padding: "16px 18px",
  marginBottom: 16,
};

const programIconStyle: React.CSSProperties = {
  width: 26,
  height: 26,
  borderRadius: 7,
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  color: chrome.amberDark,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

const programSelectStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  fontSize: 13,
  fontWeight: 500,
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  background: chrome.card,
  color: chrome.charcoal,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const factsPanelStyle: React.CSSProperties = {
  marginTop: 10,
  padding: "12px 14px",
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  borderRadius: 8,
};

const factsHeaderStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  color: chrome.amberDark,
  letterSpacing: 0.5,
  textTransform: "uppercase",
  marginBottom: 6,
};

const factsGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, 1fr)",
  gap: 8,
  marginBottom: 8,
};

const factCellStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "6px 10px",
  background: "#fff",
  border: `1px solid ${chrome.amberLight}`,
  borderRadius: 6,
};

const factLabelStyle: React.CSSProperties = {
  fontSize: 10,
  color: chrome.mutedFg,
  fontWeight: 600,
  letterSpacing: 0.3,
  textTransform: "uppercase",
};

const factValueStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 700,
  color: chrome.charcoal,
  marginLeft: 8,
};

const residualPillStyle: React.CSSProperties = {
  marginTop: 8,
  padding: "5px 10px",
  background: "#fff",
  border: `1px solid ${chrome.amberLight}`,
  borderRadius: 5,
  fontSize: 11,
  color: chrome.charcoal,
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
};

const analyzeBtnStyle: React.CSSProperties = {
  width: "100%",
  padding: "14px 20px",
  fontSize: 15,
  fontWeight: 600,
  background: chrome.amber,
  color: "#fff",
  border: "none",
  borderRadius: 8,
  fontFamily: typography.fontFamily.primary,
};

const errorStyle: React.CSSProperties = {
  background: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  padding: "8px 12px",
  fontSize: 12,
  marginBottom: 12,
};
