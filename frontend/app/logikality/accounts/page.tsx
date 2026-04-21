"use client";

/**
 * Platform-admin accounts list (US-1.5).
 *
 * Summary KPI cards on top (orgs / customer users / subscriptions), then
 * a table of every customer org with per-row counts. Backend enforces
 * role via `require_platform_admin`; `useRequireRole` here is a UX guard
 * that bounces unauthenticated or wrong-role visitors back to
 * `/logikality` (the login landing). It is NOT the security boundary.
 *
 * Subscriptions are stubbed at 0 on the API today; US-2.5 fills them in.
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
            Organizations provisioned on One Logikality. Create, edit, or remove
            accounts and manage each tenant&rsquo;s app subscriptions.
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
            </tr>
          </thead>
          <tbody>
            {accounts === null && !error ? (
              <tr>
                <td colSpan={5} style={emptyCellStyle}>
                  Loading accounts&hellip;
                </td>
              </tr>
            ) : null}
            {accounts && accounts.length === 0 ? (
              <tr>
                <td colSpan={5} style={emptyCellStyle}>
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
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
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
  margin: 0,
  fontSize: 24,
  fontWeight: typography.fontWeight.headline,
  color: chrome.charcoal,
};

const subtitleStyle: React.CSSProperties = {
  margin: "6px 0 0",
  fontSize: 14,
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
