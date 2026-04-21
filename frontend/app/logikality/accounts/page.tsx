"use client";

/**
 * Platform-admin accounts list (US-1.5 + partial US-1.7 delete).
 *
 * Summary KPI cards on top (orgs / customer users / subscriptions), then
 * a table of every customer org with per-row counts and a destructive
 * "Delete" action. Backend enforces role via `require_platform_admin`;
 * `useRequireRole` here is a UX guard that bounces unauthenticated or
 * wrong-role visitors back to `/logikality` (the login landing). It is
 * NOT the security boundary.
 *
 * Delete opens a confirm modal that surfaces the blast radius (users +
 * subscriptions about to be cascaded away). On confirm we call the
 * backend and optimistically remove the row from local state; the KPI
 * totals re-derive from the filtered array.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

type Account = {
  id: string;
  name: string;
  slug: string;
  type: string;
  created_at: string;
  user_count: number;
  subscription_count: number;
};

export default function AccountsPage() {
  const { ready } = useRequireRole(["platform_admin"], "/logikality");
  const { token } = useAuth();
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Row the admin clicked Delete on. `null` means the modal is closed.
  // We stash the whole row (not just id) so the modal can show the name
  // and the user/subscription counts without another API call.
  const [pendingDelete, setPendingDelete] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    (async () => {
      try {
        const rows = await api<Account[]>("/api/logikality/accounts", { token });
        if (!cancelled) setAccounts(rows);
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.detail ?? `Request failed (${err.status}).`
            : "Could not load accounts. Please try again.";
        setError(msg);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token]);

  async function confirmDelete() {
    if (!pendingDelete || !token) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api<void>(`/api/logikality/accounts/${pendingDelete.id}`, {
        method: "DELETE",
        token,
      });
      // Optimistic local update — no need to refetch the whole list for
      // one removal. If a parallel tab already deleted the org, the
      // backend would return 404; we translate that into a friendly
      // inline error via the ApiError path below.
      setAccounts((prev) => prev?.filter((a) => a.id !== pendingDelete.id) ?? null);
      setPendingDelete(null);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not delete account. Please try again.";
      setDeleteError(msg);
    } finally {
      setDeleting(false);
    }
  }

  function closeDeleteModal() {
    if (deleting) return;
    setPendingDelete(null);
    setDeleteError(null);
  }

  if (!ready) return null;

  const totalOrgs = accounts?.length ?? 0;
  const totalUsers = accounts?.reduce((n, a) => n + a.user_count, 0) ?? 0;
  const totalSubs = accounts?.reduce((n, a) => n + a.subscription_count, 0) ?? 0;

  return (
    <div style={pageStyle}>
      <header style={headerStyle}>
        <div>
          <h1 style={titleStyle}>Customer accounts</h1>
          <p style={subtitleStyle}>
            Manage customer organizations, subscriptions, and designated administrators.
          </p>
        </div>
        {/* New-account CTA — US-1.6 lands the form. The link is wired now
            so the IA settles before the form exists. Platform-amber matches
            the demo's PLATFORM_AMBER treatment for visual parity. */}
        <Link href="/logikality/accounts/new" className="ol-new-account-btn" style={newAccountBtnStyle}>
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          Create customer account
        </Link>
        {/* Hover state can't live on inline styles. Mirrors the demo's
            amber → amberDark transition on PLATFORM_AMBER. */}
        <style>{`
          .ol-new-account-btn { transition: background 0.15s; }
          .ol-new-account-btn:hover { background: ${chrome.amberDark}; }
        `}</style>
      </header>

      <section style={kpiRowStyle}>
        <KpiCard label="Organizations" value={totalOrgs} loading={accounts === null} />
        <KpiCard label="Customer users" value={totalUsers} loading={accounts === null} />
        <KpiCard
          label="App subscriptions"
          value={totalSubs}
          loading={accounts === null}
          hint="Populated once subscriptions ship (US-2.5)."
        />
      </section>

      {error ? (
        <div role="alert" style={errorStyle}>
          {error}
        </div>
      ) : null}

      <section style={tableWrapStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <Th>Organization</Th>
              <Th>Type</Th>
              <Th align="right">Users</Th>
              <Th align="right">Subscriptions</Th>
              <Th>Created</Th>
              <Th align="right">Actions</Th>
            </tr>
          </thead>
          <tbody>
            {accounts === null && !error ? (
              <tr>
                <td colSpan={6} style={emptyCellStyle}>
                  Loading accounts&hellip;
                </td>
              </tr>
            ) : null}
            {accounts && accounts.length === 0 ? (
              <tr>
                <td colSpan={6} style={emptyCellStyle}>
                  No customer organizations yet. Create one to get started.
                </td>
              </tr>
            ) : null}
            {accounts?.map((a) => (
              <tr key={a.id} style={rowStyle}>
                <td style={cellStyle}>
                  <div style={orgNameStyle}>{a.name}</div>
                  <div style={slugStyle}>/{a.slug}</div>
                </td>
                <td style={cellStyle}>{a.type}</td>
                <td style={{ ...cellStyle, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {a.user_count}
                </td>
                <td style={{ ...cellStyle, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {a.subscription_count}
                </td>
                <td style={cellStyle}>{formatDate(a.created_at)}</td>
                <td style={{ ...cellStyle, textAlign: "right" }}>
                  <div style={actionsCellStyle}>
                    <Link
                      href={`/logikality/accounts/${a.id}`}
                      style={manageBtnStyle}
                      aria-label={`Manage ${a.name}`}
                    >
                      Manage
                    </Link>
                    <button
                      type="button"
                      onClick={() => setPendingDelete(a)}
                      className="ol-delete-btn"
                      style={deleteBtnStyle}
                      aria-label={`Delete ${a.name}`}
                    >
                      <TrashIcon />
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {pendingDelete ? (
        <DeleteConfirmModal
          account={pendingDelete}
          onCancel={closeDeleteModal}
          onConfirm={confirmDelete}
          submitting={deleting}
          error={deleteError}
        />
      ) : null}

      {/* Destructive-button hover state. Inline styles can't hold :hover,
          so a tiny scoped stylesheet keeps the token usage consistent. */}
      <style>{`
        .ol-delete-btn { transition: background 0.15s, color 0.15s; }
        .ol-delete-btn:hover:not(:disabled) {
          background: #FEE2E2;
          color: #991B1B;
        }
      `}</style>
    </div>
  );
}

function DeleteConfirmModal({
  account,
  onCancel,
  onConfirm,
  submitting,
  error,
}: {
  account: Account;
  onCancel: () => void;
  onConfirm: () => void;
  submitting: boolean;
  error: string | null;
}) {
  return (
    <div style={modalBackdropStyle} role="dialog" aria-modal="true" aria-labelledby="delete-title">
      <div style={modalCardStyle}>
        <h2 id="delete-title" style={modalTitleStyle}>
          Delete {account.name}?
        </h2>
        <p style={modalBodyStyle}>
          This will permanently remove the organization along with{" "}
          <strong>{account.user_count}</strong>{" "}
          {account.user_count === 1 ? "user" : "users"} and{" "}
          <strong>{account.subscription_count}</strong>{" "}
          {account.subscription_count === 1 ? "app subscription" : "app subscriptions"}.
          This action cannot be undone.
        </p>
        {error ? (
          <div role="alert" style={modalErrorStyle}>
            {error}
          </div>
        ) : null}
        <div style={modalActionsStyle}>
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            style={modalCancelBtnStyle}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={submitting}
            style={{
              ...modalConfirmBtnStyle,
              opacity: submitting ? 0.7 : 1,
              cursor: submitting ? "not-allowed" : "pointer",
            }}
          >
            {submitting ? "Deleting…" : "Delete account"}
          </button>
        </div>
      </div>
    </div>
  );
}

function TrashIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
      <path d="M10 11v6M14 11v6" />
      <path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2" />
    </svg>
  );
}

function KpiCard({
  label,
  value,
  loading,
  hint,
}: {
  label: string;
  value: number;
  loading: boolean;
  hint?: string;
}) {
  return (
    <div style={kpiCardStyle}>
      <div style={kpiLabelStyle}>{label}</div>
      <div style={kpiValueStyle}>{loading ? "—" : value.toLocaleString()}</div>
      {hint ? <div style={kpiHintStyle}>{hint}</div> : null}
    </div>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th style={{ ...thStyle, textAlign: align }} scope="col">
      {children}
    </th>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/* ----- styles -------------------------------------------------------- */

const pageStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 24,
  maxWidth: 1100,
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 24,
};

const titleStyle: React.CSSProperties = {
  margin: "0 0 4px",
  fontSize: 24,
  fontWeight: typography.fontWeight.headline,
  color: chrome.charcoal,
  letterSpacing: "-0.02em",
};

const subtitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  color: chrome.mutedFg,
  lineHeight: 1.5,
  maxWidth: 640,
};

const newAccountBtnStyle: React.CSSProperties = {
  // Matches demo's PLATFORM_AMBER — the amber accent is the platform-admin
  // portal's primary CTA treatment. Teal is reserved for customer-portal CTAs.
  backgroundColor: chrome.amber,
  color: "#FFFFFF",
  padding: "10px 18px",
  borderRadius: 8,
  textDecoration: "none",
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  whiteSpace: "nowrap",
  display: "inline-flex",
  alignItems: "center",
  gap: 7,
  border: "none",
};

const kpiRowStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
  gap: 16,
};

const kpiCardStyle: React.CSSProperties = {
  backgroundColor: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 10,
  padding: "16px 18px",
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const kpiLabelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: typography.fontWeight.subheading,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: chrome.mutedFg,
};

const kpiValueStyle: React.CSSProperties = {
  fontSize: 28,
  fontWeight: typography.fontWeight.headline,
  color: chrome.charcoal,
  lineHeight: 1.1,
  fontVariantNumeric: "tabular-nums",
};

const kpiHintStyle: React.CSSProperties = {
  fontSize: 12,
  color: chrome.mutedFg,
  lineHeight: 1.4,
};

const tableWrapStyle: React.CSSProperties = {
  backgroundColor: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 10,
  overflow: "hidden",
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 14,
};

const thStyle: React.CSSProperties = {
  padding: "12px 16px",
  backgroundColor: chrome.muted,
  color: chrome.mutedFg,
  fontWeight: typography.fontWeight.subheading,
  fontSize: 12,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  borderBottom: `1px solid ${chrome.border}`,
};

const cellStyle: React.CSSProperties = {
  padding: "12px 16px",
  borderBottom: `1px solid ${chrome.border}`,
  color: chrome.fg,
  verticalAlign: "middle",
};

const rowStyle: React.CSSProperties = {
  // Last row's border is fine; a tiny visual nit we can fix later.
};

const orgNameStyle: React.CSSProperties = {
  fontWeight: typography.fontWeight.subheading,
  color: chrome.charcoal,
};

const slugStyle: React.CSSProperties = {
  fontSize: 12,
  color: chrome.mutedFg,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  marginTop: 2,
};

const emptyCellStyle: React.CSSProperties = {
  padding: "24px 16px",
  textAlign: "center",
  color: chrome.mutedFg,
};

const errorStyle: React.CSSProperties = {
  backgroundColor: "#FDECEC",
  color: "#8A1C1C",
  borderRadius: 8,
  padding: "10px 14px",
  fontSize: 14,
  lineHeight: 1.4,
};

const actionsCellStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  justifyContent: "flex-end",
};

// Neutral Manage link — primary row action but deliberately understated
// so the destructive Delete doesn't have to fight it for visual weight.
const manageBtnStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "5px 12px",
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.amber,
  background: "#fff",
  border: `1px solid ${chrome.amber}40`,
  borderRadius: 6,
  textDecoration: "none",
  fontFamily: typography.fontFamily.primary,
};

// Destructive-action button. Neutral by default, red on hover — matches
// Title Intelligence Hub's convention so destructive affordances only
// stand out when the admin is intentionally hovering them.
const deleteBtnStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  padding: "5px 12px",
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  color: "#B91C1C",
  background: "#fff",
  border: "1px solid #FCA5A5",
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const modalBackdropStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(20, 18, 14, 0.45)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  // Above the sidebar's sticky position + any future popovers.
  zIndex: 50,
  padding: 16,
};

const modalCardStyle: React.CSSProperties = {
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 12,
  padding: "22px 24px",
  maxWidth: 440,
  width: "100%",
  boxShadow: "0 10px 30px rgba(20,18,14,0.2)",
};

const modalTitleStyle: React.CSSProperties = {
  margin: "0 0 10px",
  fontSize: 17,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.charcoal,
  letterSpacing: "-0.01em",
};

const modalBodyStyle: React.CSSProperties = {
  margin: "0 0 14px",
  fontSize: 13,
  color: chrome.fg,
  lineHeight: 1.55,
};

const modalErrorStyle: React.CSSProperties = {
  background: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  padding: "8px 12px",
  fontSize: 12,
  marginBottom: 12,
};

const modalActionsStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 10,
};

const modalCancelBtnStyle: React.CSSProperties = {
  padding: "9px 16px",
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.mutedFg,
  background: "transparent",
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const modalConfirmBtnStyle: React.CSSProperties = {
  padding: "9px 16px",
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  color: "#FFFFFF",
  background: "#DC2626",
  border: "none",
  borderRadius: 8,
  fontFamily: typography.fontFamily.primary,
};
