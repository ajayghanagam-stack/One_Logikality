"use client";

/**
 * Customer-admin change-password page (US-2.1).
 *
 * Visual twin of the platform-admin page at `/logikality/profile` — same
 * lock-icon header card, three password inputs, inline error/success,
 * amber submit button — with an Administration › Change password
 * breadcrumb on top to match the other customer-admin surfaces.
 *
 * Backend endpoint is shared with US-1.8: `POST /api/auth/change-password`
 * is role-agnostic (gated only by `get_current_user`), so this page
 * reuses it without any server-side changes.
 *
 * Role enforcement: `useRequireRole("customer_admin")` bounces customer
 * users and platform admins back to the tenant root; the backend
 * re-checks auth on every call.
 */

import { useState, type FormEvent } from "react";
import { useParams } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

export default function CustomerAdminProfilePage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const { ready } = useRequireRole(["customer_admin"], `/${orgSlug}`);
  const { token, user } = useAuth();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  if (!ready) return null;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    // Client-side checks first — obvious mistakes shouldn't burn a
    // round-trip. Backend enforces `min_length=6` and "must differ from
    // current" independently.
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    if (newPassword.length < 6) {
      setError("New password must be at least 6 characters.");
      return;
    }
    if (!token) return;

    setSubmitting(true);
    try {
      await api<void>("/api/auth/change-password", {
        method: "POST",
        token,
        json: { current_password: currentPassword, new_password: newPassword },
      });
      setSuccess("Password changed successfully.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not change password. Please try again.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={pageStyle}>
      <nav style={breadcrumbStyle} aria-label="Breadcrumb">
        <span>Administration</span>
        <span style={breadcrumbSepStyle}>›</span>
        <span style={breadcrumbCurrentStyle}>Change password</span>
      </nav>

      <div style={cardWrapStyle}>
        <div style={cardStyle}>
          <div style={headerStyle}>
            <div style={headerRowStyle}>
              <LockIcon />
              <h1 style={titleStyle}>Change Password</h1>
            </div>
            <p style={subtitleStyle}>
              Update the password for {user?.email ?? "your account"}
            </p>
          </div>

          <form onSubmit={onSubmit} style={formStyle} noValidate>
            <Field label="Current Password" htmlFor="current-password">
              <input
                id="current-password"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
                minLength={1}
                autoComplete="current-password"
                style={inputStyle}
              />
            </Field>
            <Field label="New Password" htmlFor="new-password">
              <input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={6}
                maxLength={128}
                autoComplete="new-password"
                style={inputStyle}
              />
            </Field>
            <Field label="Confirm New Password" htmlFor="confirm-password">
              <input
                id="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={6}
                maxLength={128}
                autoComplete="new-password"
                style={inputStyle}
              />
            </Field>

            {error ? (
              <div role="alert" style={errorStyle}>
                {error}
              </div>
            ) : null}
            {success ? (
              <div role="status" style={successStyle}>
                {success}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={submitting}
              className="ol-cust-change-pw-btn"
              style={{
                ...primaryBtnStyle,
                opacity: submitting ? 0.7 : 1,
                cursor: submitting ? "not-allowed" : "pointer",
              }}
            >
              {submitting ? "Changing…" : "Change Password"}
            </button>
            <style>{`
              .ol-cust-change-pw-btn { transition: background 0.15s; }
              .ol-cust-change-pw-btn:hover:not(:disabled) { background: ${chrome.amberDark}; }
            `}</style>
          </form>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} style={labelStyle}>
        {label}
      </label>
      {children}
    </div>
  );
}

function LockIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke={chrome.charcoal}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="16" r="1" />
      <rect x="3" y="10" width="18" height="12" rx="2" />
      <path d="M7 10V7a5 5 0 019.9-1" />
    </svg>
  );
}

/* ----- styles -------------------------------------------------------- */

const pageStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 18,
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

// The card itself is narrow (520px) and centered within the content area,
// mirroring the demo's single-column layout for this page.
const cardWrapStyle: React.CSSProperties = {
  maxWidth: 520,
  width: "100%",
  margin: "0 auto",
};

const cardStyle: React.CSSProperties = {
  background: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 12,
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
  overflow: "hidden",
};

const headerStyle: React.CSSProperties = {
  padding: "20px 26px",
  borderBottom: `1px solid ${chrome.border}`,
};

const headerRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  marginBottom: 4,
};

const titleStyle: React.CSSProperties = {
  fontSize: 19,
  fontWeight: typography.fontWeight.subheading,
  margin: 0,
  color: chrome.charcoal,
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 13,
  color: chrome.mutedFg,
  margin: 0,
};

const formStyle: React.CSSProperties = {
  padding: "22px 26px",
  display: "flex",
  flexDirection: "column",
  gap: 14,
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 13,
  fontWeight: 500,
  color: chrome.charcoal,
  marginBottom: 6,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  fontSize: 14,
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  background: chrome.card,
  color: chrome.charcoal,
  boxSizing: "border-box",
  fontFamily: "inherit",
  outline: "none",
};

const errorStyle: React.CSSProperties = {
  fontSize: 13,
  color: "#DC2626",
};

const successStyle: React.CSSProperties = {
  fontSize: 13,
  color: "#059669",
};

const primaryBtnStyle: React.CSSProperties = {
  width: "100%",
  padding: "11px 18px",
  background: chrome.amber,
  color: "#FFFFFF",
  border: "none",
  borderRadius: 8,
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  fontFamily: "inherit",
};
