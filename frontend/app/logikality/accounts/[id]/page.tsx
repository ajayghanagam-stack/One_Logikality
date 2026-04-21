"use client";

/**
 * Platform-admin account detail / Manage page (US-1.7).
 *
 * Three cards stacked: header (org name + type + created date), designated
 * customer administrator (with Reset password button), and subscribed
 * micro-apps (per-app Enable/Disable toggle; ECV is locked on).
 *
 * Wires to three backend endpoints:
 *   - GET  /api/logikality/accounts/{id}
 *   - POST /api/logikality/accounts/{id}/reset-admin-password
 *   - PUT  /api/logikality/accounts/{id}/subscriptions
 *
 * Reset-password flow mirrors the create-account temp-password card: the
 * plaintext is returned once; the admin copies it and hands it off. No
 * rename affordance yet — demo parity; add PATCH /accounts/{id} later if
 * the product asks for it.
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { MICRO_APPS } from "@/lib/apps";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

type AccountDetail = {
  id: string;
  name: string;
  slug: string;
  type: string;
  created_at: string;
  user_count: number;
  subscription_count: number;
  primary_admin_name: string | null;
  primary_admin_email: string | null;
  subscribed_apps: string[];
};

export default function AccountDetailPage() {
  const { ready } = useRequireRole(["platform_admin"], "/logikality");
  const { token } = useAuth();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const accountId = params.id;

  const [account, setAccount] = useState<AccountDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  // Per-app-id "busy" flag so the Enable/Disable button can disable itself
  // while the PUT /subscriptions roundtrip is in flight without locking the
  // whole card.
  const [togglingApp, setTogglingApp] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token || !accountId) return;
    let cancelled = false;
    (async () => {
      try {
        const detail = await api<AccountDetail>(
          `/api/logikality/accounts/${accountId}`,
          { token },
        );
        if (!cancelled) setAccount(detail);
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.detail ?? `Request failed (${err.status}).`
            : "Could not load account. Please try again.";
        setLoadError(msg);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token, accountId]);

  async function toggleApp(appId: string) {
    if (!account || !token) return;
    if (appId === "ecv") return; // UI guard; backend forces ECV too.
    const isSubscribed = account.subscribed_apps.includes(appId);
    const nextSet = isSubscribed
      ? account.subscribed_apps.filter((a) => a !== appId)
      : [...account.subscribed_apps, appId];

    setTogglingApp(appId);
    setToggleError(null);
    try {
      const updated = await api<AccountDetail>(
        `/api/logikality/accounts/${account.id}/subscriptions`,
        { method: "PUT", token, json: { app_ids: nextSet } },
      );
      setAccount(updated);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not update subscriptions. Please try again.";
      setToggleError(msg);
    } finally {
      setTogglingApp(null);
    }
  }

  if (!ready) return null;

  return (
    <div style={pageStyle}>
      <nav style={breadcrumbStyle} aria-label="Breadcrumb">
        <Link href="/logikality/accounts" style={breadcrumbLinkStyle}>
          Customer accounts
        </Link>
        <span style={breadcrumbSepStyle}>›</span>
        <span style={breadcrumbCurrentStyle}>
          {account?.name ?? "Loading…"}
        </span>
      </nav>

      {loadError ? (
        <div role="alert" style={errorStyle}>
          {loadError}
        </div>
      ) : null}

      {account === null && !loadError ? (
        <div style={loadingStyle}>Loading account…</div>
      ) : null}

      {account ? (
        <>
          <HeaderCard account={account} />

          <AdminCard
            account={account}
            onReset={() => setResetOpen(true)}
          />

          <AppsCard
            account={account}
            togglingApp={togglingApp}
            error={toggleError}
            onToggle={toggleApp}
          />

          <div style={backRowStyle}>
            <button
              type="button"
              onClick={() => router.push("/logikality/accounts")}
              style={backBtnStyle}
            >
              <BackArrow />
              Back to accounts
            </button>
          </div>
        </>
      ) : null}

      {account && resetOpen ? (
        <ResetPasswordModal
          account={account}
          token={token}
          onClose={() => setResetOpen(false)}
          onReset={(updated) => setAccount(updated)}
        />
      ) : null}
    </div>
  );
}

/* ----- header card --------------------------------------------------- */

function HeaderCard({ account }: { account: AccountDetail }) {
  return (
    <div style={headerCardStyle}>
      <div style={headerIconStyle}>
        <BuildingIcon />
      </div>
      <div style={{ flex: 1 }}>
        <h1 style={headerTitleStyle}>{account.name}</h1>
        <div style={headerMetaStyle}>
          <span style={slugMonoStyle}>/{account.slug}</span>
          <span>·</span>
          <span style={typePillStyle}>{account.type}</span>
          <span>·</span>
          <span>Created {formatDate(account.created_at)}</span>
        </div>
      </div>
    </div>
  );
}

/* ----- admin card ---------------------------------------------------- */

function AdminCard({
  account,
  onReset,
}: {
  account: AccountDetail;
  onReset: () => void;
}) {
  const initials =
    account.primary_admin_name
      ?.split(" ")
      .map((n) => n[0])
      .filter(Boolean)
      .join("")
      .slice(0, 2)
      .toUpperCase() ?? "?";

  return (
    <section style={sectionStyle}>
      <div style={sectionHeaderStyle}>
        <h3 style={sectionTitleStyle}>Designated customer administrator</h3>
        <button
          type="button"
          onClick={onReset}
          disabled={!account.primary_admin_email}
          style={resetBtnStyle}
        >
          <LockIcon />
          Reset password
        </button>
      </div>
      <div style={adminRowStyle}>
        <div style={avatarStyle}>{initials}</div>
        <div style={{ flex: 1 }}>
          <div style={adminNameStyle}>
            {account.primary_admin_name ?? "—"}
          </div>
          <div style={adminEmailStyle}>
            {account.primary_admin_email ?? "No primary admin on file"}
          </div>
        </div>
        {account.primary_admin_email ? (
          <span style={activeBadgeStyle}>
            <CheckIcon />
            Active
          </span>
        ) : null}
      </div>
    </section>
  );
}

/* ----- reset password modal ----------------------------------------- */

function ResetPasswordModal({
  account,
  token,
  onClose,
  onReset,
}: {
  account: AccountDetail;
  token: string | null;
  onClose: () => void;
  onReset: (updated: AccountDetail) => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [issued, setIssued] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  function generate() {
    // Deliberately excludes ambiguous chars (0/O, 1/l/I) so a human can
    // read the temp password off the screen without squinting.
    const chars =
      "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789";
    let out = "";
    for (let i = 0; i < 12; i++) {
      out += chars[Math.floor(Math.random() * chars.length)];
    }
    setNewPassword(out);
  }

  async function submit() {
    if (!token || newPassword.length < 6) return;
    setSubmitting(true);
    setError(null);
    try {
      const resp = await api<{
        primary_admin_email: string;
        temp_password: string;
      }>(`/api/logikality/accounts/${account.id}/reset-admin-password`, {
        method: "POST",
        token,
        json: { new_password: newPassword },
      });
      setIssued(resp.temp_password);
      // Parent doesn't technically need a refetch (password hash is not
      // surfaced), but keeping the account object stable is tidier than
      // letting it go stale.
      onReset({ ...account });
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not reset password. Please try again.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function copy() {
    if (!issued) return;
    await navigator.clipboard.writeText(issued);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div
      onClick={onClose}
      style={modalBackdropStyle}
      role="dialog"
      aria-modal="true"
      aria-labelledby="reset-title"
    >
      <div onClick={(e) => e.stopPropagation()} style={modalCardStyle}>
        <div style={modalHeaderStyle}>
          <h2 id="reset-title" style={modalTitleStyle}>
            {issued
              ? "Password reset"
              : `Reset password for ${account.primary_admin_name ?? "admin"}`}
          </h2>
          <p style={modalSubtitleStyle}>
            {issued
              ? "Share the new password with the admin securely."
              : "Generate or set a new password. Share it with the admin securely."}
          </p>
        </div>

        <div style={modalBodyStyle}>
          {issued ? (
            <div>
              <div style={successBannerStyle}>
                Password successfully reset. The previous password is no
                longer valid. Share the new password with{" "}
                <strong>{account.primary_admin_email}</strong>.
              </div>
              <div style={copyRowStyle}>
                <code style={passwordCodeStyle}>{issued}</code>
                <button
                  type="button"
                  onClick={copy}
                  style={copyBtnStyle}
                  title="Copy password"
                >
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
          ) : (
            <div>
              <label htmlFor="new-admin-password" style={modalLabelStyle}>
                New password
              </label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  id="new-admin-password"
                  type="text"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Enter or generate password"
                  minLength={6}
                  maxLength={128}
                  style={modalInputStyle}
                  autoComplete="off"
                />
                <button type="button" onClick={generate} style={generateBtnStyle}>
                  Generate
                </button>
              </div>
              <div style={modalHintStyle}>
                Minimum 6 characters. This replaces the current password
                immediately.
              </div>
              {error ? (
                <div role="alert" style={inlineErrorStyle}>
                  {error}
                </div>
              ) : null}
            </div>
          )}
        </div>

        <div style={modalFooterStyle}>
          {issued ? (
            <button type="button" onClick={onClose} style={primaryBtnStyle}>
              Close
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                style={secondaryBtnStyle}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={submitting || newPassword.length < 6}
                style={{
                  ...primaryBtnStyle,
                  opacity: submitting || newPassword.length < 6 ? 0.5 : 1,
                  cursor:
                    submitting || newPassword.length < 6
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                {submitting ? "Resetting…" : "Reset password"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ----- apps card ----------------------------------------------------- */

function AppsCard({
  account,
  togglingApp,
  error,
  onToggle,
}: {
  account: AccountDetail;
  togglingApp: string | null;
  error: string | null;
  onToggle: (appId: string) => void;
}) {
  return (
    <section style={sectionStyle}>
      <h3 style={sectionTitleStyle}>Subscribed micro-apps</h3>
      <p style={sectionHintStyle}>
        Enable or disable micro-apps for this customer. Changes are
        effective immediately and impact the customer&rsquo;s billing. ECV
        is required and cannot be unsubscribed.
      </p>
      {error ? (
        <div role="alert" style={inlineErrorStyle}>
          {error}
        </div>
      ) : null}
      <div style={appsListStyle}>
        {MICRO_APPS.map((app) => {
          const isEcv = app.id === "ecv";
          const isSubscribed = account.subscribed_apps.includes(app.id);
          const busy = togglingApp === app.id;
          return (
            <div
              key={app.id}
              style={{
                ...appRowStyle,
                background: isSubscribed ? chrome.card : `${chrome.muted}80`,
              }}
            >
              <span style={{ fontSize: 20 }} aria-hidden="true">
                {app.icon}
              </span>
              <div style={{ flex: 1 }}>
                <div style={appNameStyle}>
                  {app.name}
                  {isEcv ? <span style={requiredBadgeStyle}>Required</span> : null}
                </div>
                <div style={appDescStyle}>{app.desc}</div>
              </div>
              <div style={appActionsStyle}>
                <span
                  style={{
                    ...subscribedPillStyle,
                    background: isSubscribed ? "#D1FAE5" : chrome.muted,
                    borderColor: isSubscribed ? "#A7F3D0" : chrome.border,
                    color: isSubscribed ? "#065F46" : chrome.mutedFg,
                  }}
                >
                  {isSubscribed ? "Subscribed" : "Not subscribed"}
                </span>
                <button
                  type="button"
                  onClick={() => onToggle(app.id)}
                  disabled={isEcv || busy}
                  style={{
                    ...toggleBtnStyle,
                    background: isSubscribed ? "#fff" : chrome.amber,
                    color: isSubscribed ? "#B91C1C" : "#fff",
                    border: isSubscribed ? "1px solid #FCA5A5" : "none",
                    opacity: isEcv ? 0.5 : busy ? 0.7 : 1,
                    cursor: isEcv || busy ? "not-allowed" : "pointer",
                  }}
                >
                  {busy ? "…" : isSubscribed ? "Disable" : "Enable"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* ----- icons --------------------------------------------------------- */

function BuildingIcon() {
  return (
    <svg
      width="26"
      height="26"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4M9 9v.01M9 12v.01M9 15v.01M9 18v.01" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0110 0v4" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      width="9"
      height="9"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function BackArrow() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  );
}

/* ----- helpers ------------------------------------------------------- */

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/* ----- styles -------------------------------------------------------- */

const pageStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  maxWidth: 900,
};

const breadcrumbStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  fontSize: 12,
  color: chrome.mutedFg,
  marginBottom: 4,
};

const breadcrumbLinkStyle: React.CSSProperties = {
  color: chrome.amber,
  textDecoration: "none",
  fontWeight: typography.fontWeight.subheading,
};

const breadcrumbSepStyle: React.CSSProperties = { color: chrome.mutedFg };

const breadcrumbCurrentStyle: React.CSSProperties = {
  color: chrome.charcoal,
  fontWeight: 500,
};

const errorStyle: React.CSSProperties = {
  background: "#FDECEC",
  color: "#8A1C1C",
  borderRadius: 8,
  padding: "10px 14px",
  fontSize: 14,
};

const loadingStyle: React.CSSProperties = {
  padding: "24px",
  color: chrome.mutedFg,
  fontSize: 14,
};

const headerCardStyle: React.CSSProperties = {
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 12,
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
  padding: "22px 26px",
  display: "flex",
  alignItems: "center",
  gap: 16,
};

const headerIconStyle: React.CSSProperties = {
  width: 54,
  height: 54,
  borderRadius: 12,
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  color: chrome.amber,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

const headerTitleStyle: React.CSSProperties = {
  fontSize: 22,
  fontWeight: typography.fontWeight.headline,
  margin: "0 0 4px",
  color: chrome.charcoal,
  letterSpacing: "-0.02em",
};

const headerMetaStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  fontSize: 12,
  color: chrome.mutedFg,
  flexWrap: "wrap",
};

const slugMonoStyle: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
};

const typePillStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "1px 8px",
  borderRadius: 10,
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  fontSize: 10,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.amber,
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const sectionStyle: React.CSSProperties = {
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 12,
  padding: "18px 22px",
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
};

const sectionHeaderStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  marginBottom: 14,
};

const sectionTitleStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  margin: 0,
  color: chrome.charcoal,
};

const sectionHintStyle: React.CSSProperties = {
  fontSize: 12,
  color: chrome.mutedFg,
  margin: "0 0 14px",
  lineHeight: 1.5,
};

const resetBtnStyle: React.CSSProperties = {
  padding: "7px 14px",
  fontSize: 12,
  fontWeight: typography.fontWeight.subheading,
  background: "#fff",
  color: chrome.amber,
  border: `1px solid ${chrome.amber}40`,
  borderRadius: 6,
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const adminRowStyle: React.CSSProperties = {
  padding: "14px 18px",
  background: chrome.muted,
  borderRadius: 8,
  display: "flex",
  alignItems: "center",
  gap: 16,
};

const avatarStyle: React.CSSProperties = {
  width: 44,
  height: 44,
  borderRadius: "50%",
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  color: chrome.amber,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 18,
  fontWeight: typography.fontWeight.subheading,
};

const adminNameStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.charcoal,
};

const adminEmailStyle: React.CSSProperties = {
  fontSize: 12,
  color: chrome.mutedFg,
  marginTop: 2,
};

const activeBadgeStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  padding: "3px 10px",
  borderRadius: 12,
  background: "#D1FAE5",
  border: "1px solid #A7F3D0",
  fontSize: 10,
  fontWeight: typography.fontWeight.subheading,
  color: "#065F46",
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const appsListStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const appRowStyle: React.CSSProperties = {
  padding: "12px 16px",
  border: `1px solid ${chrome.border}`,
  borderRadius: 9,
  display: "flex",
  alignItems: "center",
  gap: 12,
};

const appNameStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.charcoal,
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const requiredBadgeStyle: React.CSSProperties = {
  fontSize: 9,
  fontWeight: typography.fontWeight.subheading,
  padding: "1px 7px",
  borderRadius: 10,
  background: chrome.amberLight,
  color: chrome.amberDark,
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const appDescStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
  marginTop: 1,
};

const appActionsStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
};

const subscribedPillStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "3px 10px",
  borderRadius: 12,
  border: "1px solid",
  fontSize: 10,
  fontWeight: typography.fontWeight.subheading,
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const toggleBtnStyle: React.CSSProperties = {
  padding: "6px 14px",
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  borderRadius: 6,
  minWidth: 80,
  fontFamily: typography.fontFamily.primary,
};

const inlineErrorStyle: React.CSSProperties = {
  background: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  padding: "8px 12px",
  fontSize: 12,
  marginBottom: 12,
};

const backRowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "flex-start",
  marginTop: 4,
};

const backBtnStyle: React.CSSProperties = {
  padding: "9px 16px",
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.mutedFg,
  background: "transparent",
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

/* ----- modal styles -------------------------------------------------- */

const modalBackdropStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(20, 18, 14, 0.5)",
  backdropFilter: "blur(4px)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
  padding: 20,
};

const modalCardStyle: React.CSSProperties = {
  background: chrome.card,
  borderRadius: 14,
  width: "100%",
  maxWidth: 520,
  boxShadow: "0 24px 50px rgba(20, 18, 14, 0.25)",
  border: `1px solid ${chrome.border}`,
  overflow: "hidden",
};

const modalHeaderStyle: React.CSSProperties = {
  padding: "20px 26px",
  borderBottom: `1px solid ${chrome.border}`,
  background: `linear-gradient(to right, ${chrome.amberBg}, ${chrome.amberBg}40)`,
};

const modalTitleStyle: React.CSSProperties = {
  fontSize: 17,
  fontWeight: typography.fontWeight.subheading,
  margin: 0,
  color: chrome.charcoal,
};

const modalSubtitleStyle: React.CSSProperties = {
  fontSize: 12,
  color: chrome.mutedFg,
  margin: "3px 0 0",
};

const modalBodyStyle: React.CSSProperties = {
  padding: "22px 26px",
};

const modalLabelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.mutedFg,
  letterSpacing: 0.4,
  textTransform: "uppercase",
  marginBottom: 6,
};

const modalInputStyle: React.CSSProperties = {
  flex: 1,
  padding: "10px 12px",
  fontSize: 14,
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  background: chrome.card,
  color: chrome.charcoal,
  boxSizing: "border-box",
  fontFamily: typography.fontFamily.primary,
  outline: "none",
};

const modalHintStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
  marginTop: 8,
};

const generateBtnStyle: React.CSSProperties = {
  padding: "0 16px",
  fontSize: 12,
  fontWeight: typography.fontWeight.subheading,
  background: "#fff",
  color: chrome.amber,
  border: `1px solid ${chrome.amber}40`,
  borderRadius: 6,
  cursor: "pointer",
  whiteSpace: "nowrap",
  fontFamily: typography.fontFamily.primary,
};

const successBannerStyle: React.CSSProperties = {
  padding: "14px 16px",
  background: "#D1FAE5",
  border: "1px solid #A7F3D0",
  borderRadius: 9,
  marginBottom: 14,
  fontSize: 13,
  color: "#065F46",
  lineHeight: 1.5,
};

const copyRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const passwordCodeStyle: React.CSSProperties = {
  flex: 1,
  padding: "10px 14px",
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  borderRadius: 6,
  fontSize: 14,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontWeight: typography.fontWeight.subheading,
  color: chrome.charcoal,
  letterSpacing: 0.5,
};

const copyBtnStyle: React.CSSProperties = {
  padding: "8px 14px",
  fontSize: 12,
  fontWeight: typography.fontWeight.subheading,
  background: "#fff",
  color: chrome.charcoal,
  border: `1px solid ${chrome.border}`,
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const modalFooterStyle: React.CSSProperties = {
  padding: "14px 26px",
  borderTop: `1px solid ${chrome.border}`,
  background: `${chrome.muted}80`,
  display: "flex",
  justifyContent: "flex-end",
  gap: 8,
};

const primaryBtnStyle: React.CSSProperties = {
  padding: "9px 18px",
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  background: chrome.amber,
  color: "#fff",
  border: "none",
  borderRadius: 8,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const secondaryBtnStyle: React.CSSProperties = {
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
