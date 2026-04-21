"use client";

/**
 * Customer-admin App access page (US-2.5 / US-2.6).
 *
 * Two sections: subscribed apps the admin can toggle (Enable / Disable,
 * with ECV locked on), and unsubscribed apps shown read-only with a
 * "Contact sales" affordance. Structure and copy are a direct port of
 * the `one-logikality-demo` reference so the two products keep their
 * visual parity.
 *
 * Backend endpoints: `GET /api/customer-admin/apps` (every known app
 * with its subscribed/enabled state) and `PATCH /api/customer-admin/apps/{id}`
 * (toggle `enabled`; ECV-disable and unsubscribed ids are server-rejected).
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { MICRO_APPS } from "@/lib/apps";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

type AppAccessRow = {
  id: string;
  subscribed: boolean;
  enabled: boolean;
};

// Merge the server's per-org state with the static catalog (name/desc/icon).
// Server is source of truth for subscribed/enabled; catalog only contributes
// display copy. Unknown ids from the server are dropped — if the backend
// ever adds an app without updating `apps.ts`, it simply doesn't render.
type DisplayRow = AppAccessRow & {
  name: string;
  desc: string;
  icon: string;
  required: boolean;
};

export default function CustomerAdminAppsPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const { ready } = useRequireRole(["customer_admin"], `/${orgSlug}`);
  const { token } = useAuth();

  const [rows, setRows] = useState<DisplayRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Per-row in-flight + error state. Keyed by app id so one row flipping
  // doesn't disable every button on the page.
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api<AppAccessRow[]>("/api/customer-admin/apps", { token });
        if (cancelled) return;
        setRows(mergeWithCatalog(data));
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.detail ?? `Request failed (${err.status}).`
            : "Could not load app access. Please try again.";
        setLoadError(msg);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token]);

  async function toggle(id: string, next: boolean) {
    if (!token) return;
    setPendingId(id);
    setRowError(null);
    try {
      const updated = await api<AppAccessRow>(`/api/customer-admin/apps/${id}`, {
        method: "PATCH",
        token,
        json: { enabled: next },
      });
      setRows((prev) =>
        prev
          ? prev.map((r) =>
              r.id === id ? { ...r, subscribed: updated.subscribed, enabled: updated.enabled } : r,
            )
          : prev,
      );
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not update app. Please try again.";
      setRowError(msg);
    } finally {
      setPendingId(null);
    }
  }

  if (!ready) return null;

  const subscribed = rows?.filter((r) => r.subscribed) ?? [];
  const unsubscribed = rows?.filter((r) => !r.subscribed) ?? [];
  const enabledCount = subscribed.filter((r) => r.enabled).length;

  return (
    <div style={pageStyle}>
      <nav style={breadcrumbStyle} aria-label="Breadcrumb">
        <span>Administration</span>
        <span style={breadcrumbSepStyle}>›</span>
        <span style={breadcrumbCurrentStyle}>App access</span>
      </nav>

      <header>
        <h1 style={titleStyle}>App access</h1>
        <p style={subtitleStyle}>
          Enable or disable micro-apps for your organization&rsquo;s users.
          Only subscribed apps can be enabled. To add or remove subscriptions,
          contact Logikality support.
        </p>
      </header>

      {loadError ? (
        <div role="alert" style={pageErrorStyle}>
          {loadError}
        </div>
      ) : null}
      {rowError ? (
        <div role="alert" style={pageErrorStyle}>
          {rowError}
        </div>
      ) : null}

      {rows === null && !loadError ? (
        <div style={emptyRowStyle}>Loading app access…</div>
      ) : null}

      {rows ? (
        <>
          <section style={cardStyle}>
            <div style={sectionHeaderStyle}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span aria-hidden="true" style={{ fontSize: 15 }}>🧩</span>
                <h3 style={cardTitleStyle}>
                  Subscribed apps ({subscribed.length})
                </h3>
              </div>
              <span style={sectionMetaStyle}>
                {enabledCount} of {subscribed.length} enabled
              </span>
            </div>
            <div>
              {subscribed.length === 0 ? (
                <div style={emptyRowStyle}>
                  No subscribed apps yet. Contact Logikality support to add apps.
                </div>
              ) : (
                subscribed.map((app) => (
                  <SubscribedRow
                    key={app.id}
                    app={app}
                    pending={pendingId === app.id}
                    onToggle={(next) => toggle(app.id, next)}
                  />
                ))
              )}
            </div>
          </section>

          {unsubscribed.length > 0 ? (
            <section style={cardStyle}>
              <div style={sectionHeaderStyle}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span aria-hidden="true" style={{ fontSize: 15 }}>🔒</span>
                  <h3 style={cardTitleStyle}>
                    Available to purchase ({unsubscribed.length})
                  </h3>
                </div>
              </div>
              <div>
                {unsubscribed.map((app) => (
                  <UnsubscribedRow key={app.id} app={app} />
                ))}
              </div>
            </section>
          ) : null}

          <div style={noteStyle}>
            <span aria-hidden="true" style={{ fontSize: 14, marginTop: 1 }}>ℹ️</span>
            <div style={{ flex: 1, lineHeight: 1.5 }}>
              <span style={{ fontWeight: typography.fontWeight.subheading }}>
                About app access:
              </span>{" "}
              Disabling an app hides it from all users in your organization
              but preserves all historical data. Your Logikality subscription
              is not affected. To change subscriptions, contact Logikality
              support.
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

/* ----- rows ---------------------------------------------------------- */

function SubscribedRow({
  app,
  pending,
  onToggle,
}: {
  app: DisplayRow;
  pending: boolean;
  onToggle: (next: boolean) => void;
}) {
  const isRequired = app.required;
  return (
    <div style={rowStyle}>
      <span aria-hidden="true" style={{ fontSize: 22 }}>
        {app.icon}
      </span>
      <div style={{ flex: 1 }}>
        <div style={rowNameStyle}>
          {app.name}
          {isRequired ? <span style={requiredPillStyle}>Required</span> : null}
        </div>
        <div style={rowDescStyle}>{app.desc}</div>
      </div>
      <span
        style={{
          ...statusPillStyle,
          background: app.enabled ? "#D1FAE5" : chrome.muted,
          borderColor: app.enabled ? "#A7F3D0" : chrome.border,
          color: app.enabled ? "#065F46" : chrome.mutedFg,
        }}
      >
        {app.enabled ? "Enabled" : "Disabled"}
      </span>
      <button
        type="button"
        onClick={() => !isRequired && onToggle(!app.enabled)}
        disabled={isRequired || pending}
        style={{
          ...toggleBtnStyle,
          background: app.enabled ? "#fff" : chrome.amber,
          color: app.enabled ? "#B91C1C" : "#fff",
          border: app.enabled ? "1px solid #FCA5A5" : "none",
          cursor: isRequired ? "not-allowed" : pending ? "progress" : "pointer",
          opacity: isRequired ? 0.5 : pending ? 0.7 : 1,
        }}
      >
        {pending ? "…" : app.enabled ? "Disable" : "Enable"}
      </button>
    </div>
  );
}

function UnsubscribedRow({ app }: { app: DisplayRow }) {
  return (
    <div style={{ ...rowStyle, opacity: 0.75 }}>
      <span aria-hidden="true" style={{ fontSize: 22, filter: "grayscale(0.6)" }}>
        {app.icon}
      </span>
      <div style={{ flex: 1 }}>
        <div style={rowNameStyle}>{app.name}</div>
        <div style={rowDescStyle}>{app.desc}</div>
      </div>
      <span
        style={{
          ...statusPillStyle,
          background: chrome.muted,
          borderColor: chrome.border,
          color: chrome.mutedFg,
        }}
      >
        Not subscribed
      </span>
      <button
        type="button"
        onClick={() =>
          alert(
            "Contact Logikality sales to add this subscription to your account.",
          )
        }
        style={contactBtnStyle}
      >
        Contact sales
      </button>
    </div>
  );
}

/* ----- helpers ------------------------------------------------------- */

function mergeWithCatalog(server: AppAccessRow[]): DisplayRow[] {
  const order = new Map(MICRO_APPS.map((a, i) => [a.id, i] as const));
  return server
    .flatMap((s) => {
      const meta = MICRO_APPS.find((m) => m.id === s.id);
      if (!meta) return [];
      return [
        {
          ...s,
          name: meta.name,
          desc: meta.desc,
          icon: meta.icon,
          required: meta.required,
        },
      ];
    })
    .sort((a, b) => (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99));
}

/* ----- styles -------------------------------------------------------- */

const pageStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 18,
  maxWidth: 900,
};

const breadcrumbStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  fontSize: 12,
  color: chrome.mutedFg,
};

const breadcrumbSepStyle: React.CSSProperties = { color: chrome.mutedFg };

const breadcrumbCurrentStyle: React.CSSProperties = {
  color: chrome.charcoal,
  fontWeight: 500,
};

const titleStyle: React.CSSProperties = {
  fontSize: 24,
  fontWeight: typography.fontWeight.headline,
  margin: "0 0 4px",
  color: chrome.charcoal,
  letterSpacing: "-0.02em",
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 13,
  color: chrome.mutedFg,
  margin: 0,
  lineHeight: 1.5,
};

const cardStyle: React.CSSProperties = {
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 12,
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
  overflow: "hidden",
};

const sectionHeaderStyle: React.CSSProperties = {
  padding: "14px 20px",
  borderBottom: `1px solid ${chrome.border}`,
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
};

const cardTitleStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  margin: 0,
  color: chrome.charcoal,
};

const sectionMetaStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
};

const rowStyle: React.CSSProperties = {
  padding: "14px 20px",
  borderBottom: `1px solid ${chrome.border}`,
  display: "flex",
  alignItems: "center",
  gap: 14,
};

const rowNameStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.charcoal,
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const rowDescStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
  marginTop: 2,
};

const statusPillStyle: React.CSSProperties = {
  padding: "3px 10px",
  borderRadius: 12,
  border: "1px solid",
  fontSize: 10,
  fontWeight: typography.fontWeight.subheading,
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const requiredPillStyle: React.CSSProperties = {
  fontSize: 9,
  fontWeight: typography.fontWeight.subheading,
  padding: "1px 7px",
  borderRadius: 10,
  background: chrome.amberLight,
  color: chrome.amberDark,
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const toggleBtnStyle: React.CSSProperties = {
  padding: "7px 14px",
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  borderRadius: 6,
  minWidth: 80,
  fontFamily: typography.fontFamily.primary,
};

const contactBtnStyle: React.CSSProperties = {
  padding: "7px 14px",
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  background: "#fff",
  color: chrome.charcoal,
  border: `1px solid ${chrome.border}`,
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const noteStyle: React.CSSProperties = {
  padding: "12px 16px",
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  borderRadius: 8,
  fontSize: 12,
  color: chrome.amberDark,
  display: "flex",
  alignItems: "flex-start",
  gap: 10,
};

const pageErrorStyle: React.CSSProperties = {
  background: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  padding: "8px 12px",
  fontSize: 12,
};

const emptyRowStyle: React.CSSProperties = {
  padding: "30px 20px",
  textAlign: "center",
  color: chrome.mutedFg,
  fontSize: 13,
};
