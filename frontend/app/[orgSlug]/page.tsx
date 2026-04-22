"use client";

/**
 * Tenant landing — `/acme`, `/foo`, whatever the URL slug is.
 *
 *   - Unauthenticated visitor: render the login form (the tenant URL *is*
 *     the login surface, per the UX request).
 *   - Authenticated user whose own org_slug matches: render the customer
 *     home dashboard with the org's uploaded packets.
 *   - Authenticated user whose org_slug does NOT match: bounce them to
 *     their own `/{user.org_slug}`. Platform admins here get sent to
 *     `/logikality/accounts`.
 *
 * Deeper routes (e.g. `/acme/ecv`) use `useRequireRole(..., "/<slug>")`
 * so unauthenticated hits fall back to this login landing, not somewhere
 * else.
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthBrandPanel } from "@/components/auth-brand-panel";
import { LoginForm } from "@/components/login-form";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";
import { LOAN_PROGRAMS } from "@/lib/rules";

type PacketFileRow = {
  id: string;
  filename: string;
  size_bytes: number;
  content_type: string;
};

type PacketRow = {
  id: string;
  declared_program_id: string;
  status: string;
  current_stage: string | null;
  started_processing_at: string | null;
  completed_at: string | null;
  created_at: string;
  files: PacketFileRow[];
};

export default function TenantLanding() {
  const { user, hydrated, token } = useAuth();
  const params = useParams();
  const router = useRouter();
  const orgSlug = typeof params.orgSlug === "string" ? params.orgSlug : "";

  useEffect(() => {
    if (!hydrated || !user) return;
    if (user.role === "platform_admin") {
      router.replace("/logikality/accounts");
    } else if (user.org_slug && user.org_slug !== orgSlug) {
      router.replace(`/${user.org_slug}`);
    }
  }, [hydrated, user, orgSlug, router]);

  if (!hydrated) return null;

  const onOwnTenant =
    user &&
    (user.role === "customer_admin" || user.role === "customer_user") &&
    user.org_slug === orgSlug;

  if (onOwnTenant) {
    return <PacketList orgSlug={orgSlug} firstName={user.full_name.split(" ")[0]} token={token} />;
  }

  // Either no user yet, or an authenticated user on the wrong tenant URL
  // (redirect is firing from the useEffect above). Show login in both
  // cases; the redirect will swap the page out shortly after.
  if (user) return null;

  return (
    <AuthBrandPanel>
      <LoginForm
        heading="Welcome back"
        subheading="Sign in to your organization to continue."
        allowedRoles={["customer_admin", "customer_user"]}
        destinationFor={(u) => `/${u.org_slug ?? ""}`}
      />
    </AuthBrandPanel>
  );
}

/* ----- packet list --------------------------------------------------- */

function PacketList({
  orgSlug,
  firstName,
  token,
}: {
  orgSlug: string;
  firstName: string;
  token: string | null;
}) {
  const [packets, setPackets] = useState<PacketRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const rows = await api<PacketRow[]>("/api/packets", { token });
        if (!cancelled) setPackets(rows);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? (err.detail ?? `Couldn't load packets (${err.status}).`)
            : "Couldn't load packets.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  function handleDeleted(id: string) {
    setPackets((prev) => prev?.filter((p) => p.id !== id) ?? prev);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 920 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <h1
          style={{
            margin: 0,
            fontSize: 24,
            fontWeight: typography.fontWeight.headline,
            color: chrome.charcoal,
          }}
        >
          Welcome, {firstName}.
        </h1>
        <p style={{ margin: 0, color: chrome.mutedFg, lineHeight: 1.5 }}>
          Your recent uploads — pick one to open its ECV Dashboard, or upload a new packet.
        </p>
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        <Link href={`/${orgSlug}/upload`} style={primaryBtnStyle}>
          Upload a packet
        </Link>
      </div>

      {error ? (
        <div role="alert" style={errorBoxStyle}>
          {error}
        </div>
      ) : packets === null ? (
        <p style={{ margin: 0, color: chrome.mutedFg }}>Loading packets…</p>
      ) : packets.length === 0 ? (
        <div style={emptyCardStyle}>
          <p style={{ margin: 0, color: chrome.charcoal, fontWeight: 600 }}>
            No packets yet.
          </p>
          <p style={{ margin: 0, color: chrome.mutedFg }}>
            Upload your first packet to see ECV results here.
          </p>
        </div>
      ) : (
        <ul style={listStyle}>
          {packets.map((p) => (
            <PacketRowItem key={p.id} packet={p} orgSlug={orgSlug} token={token} onDeleted={handleDeleted} />
          ))}
        </ul>
      )}
    </div>
  );
}

function PacketRowItem({
  packet,
  orgSlug,
  token,
  onDeleted,
}: {
  packet: PacketRow;
  orgSlug: string;
  token: string | null;
  onDeleted: (id: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const programLabel = LOAN_PROGRAMS[packet.declared_program_id]?.label ?? packet.declared_program_id;
  const fileSummary =
    packet.files.length === 0
      ? "no files"
      : packet.files.length === 1
        ? packet.files[0].filename
        : `${packet.files[0].filename} +${packet.files.length - 1} more`;
  const created = new Date(packet.created_at).toLocaleString();
  const statusPill = statusPillStyle(packet.status);
  const isCompleted = packet.status === "completed";
  const href = `/${orgSlug}/ecv?packet=${packet.id}`;

  async function handleDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDeleting(true);
    setDeleteError(null);
    try {
      await api(`/api/packets/${packet.id}`, { method: "DELETE", token });
      onDeleted(packet.id);
    } catch (err) {
      setDeleteError(
        err instanceof ApiError
          ? (err.detail ?? "Delete failed.")
          : "Delete failed.",
      );
      setDeleting(false);
      setConfirming(false);
    }
  }

  const deleteControls = confirming ? (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }} onClick={(e) => e.stopPropagation()}>
      <span style={{ fontSize: 12, color: chrome.mutedFg }}>Delete?</span>
      <button
        onClick={handleDelete}
        disabled={deleting}
        style={deleteBtnConfirmStyle}
      >
        {deleting ? "…" : "Yes"}
      </button>
      <button
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setConfirming(false); }}
        style={deleteBtnCancelStyle}
      >
        No
      </button>
    </div>
  ) : (
    <button
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); setConfirming(true); }}
      title="Delete packet"
      style={deleteIconBtnStyle}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="3 6 5 6 21 6"/>
        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
        <path d="M10 11v6M14 11v6"/>
        <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
      </svg>
    </button>
  );

  const body = (
    <div style={rowBodyStyle}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, color: chrome.charcoal, fontSize: 14 }}>
          {fileSummary}
        </div>
        <div style={{ color: chrome.mutedFg, fontSize: 12 }}>
          {programLabel} · uploaded {created}
        </div>
        {deleteError && (
          <div style={{ fontSize: 11, color: "#991B1B", marginTop: 2 }}>{deleteError}</div>
        )}
      </div>
      <span style={statusPill.style}>{statusPill.label}</span>
      {deleteControls}
    </div>
  );

  if (isCompleted) {
    return (
      <li>
        <Link href={href} style={rowLinkStyle}>
          {body}
        </Link>
      </li>
    );
  }
  return <li style={rowStaticStyle}>{body}</li>;
}

function statusPillStyle(status: string): { label: string; style: React.CSSProperties } {
  // Keep colors restrained — the row itself is the primary surface, the
  // pill is secondary information. Uses chrome tokens + the existing
  // success/destructive semantic colors from the ECV page.
  const base: React.CSSProperties = {
    padding: "2px 10px",
    borderRadius: 999,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  };
  if (status === "completed") {
    return {
      label: "Completed",
      style: { ...base, background: "#D1FAE5", color: "#065F46" },
    };
  }
  if (status === "processing") {
    return {
      label: "Processing",
      style: { ...base, background: chrome.amberBg, color: chrome.amberDark },
    };
  }
  if (status === "failed") {
    return {
      label: "Failed",
      style: { ...base, background: "#FEE2E2", color: "#991B1B" },
    };
  }
  // "uploaded" and any future statuses fall back to a neutral pill.
  return {
    label: status,
    style: { ...base, background: chrome.muted, color: chrome.mutedFg },
  };
}

const primaryBtnStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "8px 14px",
  background: chrome.amber,
  color: chrome.card,
  borderRadius: 6,
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
};

const listStyle: React.CSSProperties = {
  listStyle: "none",
  padding: 0,
  margin: 0,
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const rowLinkStyle: React.CSSProperties = {
  display: "block",
  padding: "14px 16px",
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  textDecoration: "none",
  color: "inherit",
};

const rowStaticStyle: React.CSSProperties = {
  padding: "14px 16px",
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  opacity: 0.75,
};

const rowBodyStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
};

const emptyCardStyle: React.CSSProperties = {
  padding: "16px 18px",
  background: chrome.card,
  border: `1px dashed ${chrome.border}`,
  borderRadius: 8,
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const errorBoxStyle: React.CSSProperties = {
  padding: "12px 14px",
  background: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  fontSize: 13,
};

const deleteIconBtnStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: 6,
  background: "transparent",
  border: "none",
  borderRadius: 4,
  color: chrome.mutedFg,
  cursor: "pointer",
  flexShrink: 0,
};

const deleteBtnConfirmStyle: React.CSSProperties = {
  padding: "2px 10px",
  background: "#DC2626",
  color: "#fff",
  border: "none",
  borderRadius: 4,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};

const deleteBtnCancelStyle: React.CSSProperties = {
  padding: "2px 10px",
  background: chrome.muted,
  color: chrome.charcoal,
  border: "none",
  borderRadius: 4,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};
