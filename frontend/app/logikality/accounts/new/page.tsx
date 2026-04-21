"use client";

/**
 * Create customer account (US-1.6).
 *
 * Platform-admin-only form that provisions an org + its primary
 * customer admin in one round-trip. On success the API returns a
 * one-time temp password — we hand it to the admin with copy-to-
 * clipboard so it can be relayed to the new customer admin. The
 * plaintext is never retrievable again, so the success state
 * intentionally blocks easy dismissal (no auto-redirect).
 *
 * Role enforcement: `useRequireRole` is a UX guard; the backend
 * gates the endpoint with `require_platform_admin`.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api, ApiError } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

// Mirrors `ORG_TYPES` in backend/app/models.py. Kept in lockstep by hand;
// if this list grows, surface it from the backend via a config endpoint.
const ORG_TYPES = [
  "Mortgage Lender",
  "Loan Servicer",
  "Title Agency",
  "Mortgage BPO",
] as const;

type OrgType = (typeof ORG_TYPES)[number];

type CreateResponse = {
  account: {
    id: string;
    name: string;
    slug: string;
    type: string;
    created_at: string;
    user_count: number;
    subscription_count: number;
  };
  primary_admin_email: string;
  temp_password: string;
};

export default function NewAccountPage() {
  const { ready } = useRequireRole(["platform_admin"], "/logikality");
  const { token } = useAuth();
  const router = useRouter();

  const [name, setName] = useState("");
  const [type, setType] = useState<OrgType>(ORG_TYPES[0]);
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreateResponse | null>(null);
  const [copied, setCopied] = useState(false);

  if (!ready) return null;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      const resp = await api<CreateResponse>("/api/logikality/accounts", {
        method: "POST",
        token,
        json: {
          name: name.trim(),
          type,
          primary_admin_full_name: adminName.trim(),
          primary_admin_email: adminEmail.trim(),
        },
      });
      setCreated(resp);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not create account. Please try again.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function copyPassword() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.temp_password);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard may be unavailable (insecure context, permissions). The
      // password is still visible on screen as a fallback — no alert needed.
    }
  }

  return (
    <div style={pageStyle}>
      <nav style={breadcrumbStyle}>
        <Link href="/logikality/accounts" style={breadcrumbLinkStyle}>
          ← Back to accounts
        </Link>
      </nav>

      <header>
        <h1 style={titleStyle}>Create customer account</h1>
        <p style={subtitleStyle}>
          Provision a new customer organization and its primary admin. The
          admin receives a one-time temporary password to share with the
          customer — copy it from the confirmation screen before navigating
          away.
        </p>
      </header>

      {created ? (
        <SuccessPanel
          created={created}
          copied={copied}
          onCopy={copyPassword}
          onDone={() => router.push("/logikality/accounts")}
        />
      ) : (
        <form onSubmit={onSubmit} style={formStyle} noValidate>
          <Field label="Organization name" htmlFor="org-name" required>
            <input
              id="org-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={120}
              autoComplete="off"
              style={inputStyle}
              placeholder="Acme Mortgage Holdings"
            />
          </Field>

          <Field label="Organization type" htmlFor="org-type" required>
            <select
              id="org-type"
              value={type}
              onChange={(e) => setType(e.target.value as OrgType)}
              required
              style={inputStyle}
            >
              {ORG_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Primary admin name" htmlFor="admin-name" required>
            <input
              id="admin-name"
              type="text"
              value={adminName}
              onChange={(e) => setAdminName(e.target.value)}
              required
              maxLength={120}
              autoComplete="off"
              style={inputStyle}
              placeholder="Jane Underwriter"
            />
          </Field>

          <Field label="Primary admin email" htmlFor="admin-email" required>
            <input
              id="admin-email"
              type="email"
              value={adminEmail}
              onChange={(e) => setAdminEmail(e.target.value)}
              required
              autoComplete="off"
              style={inputStyle}
              placeholder="jane@acmemortgage.com"
            />
          </Field>

          {error ? (
            <div role="alert" style={errorStyle}>
              {error}
            </div>
          ) : null}

          <div style={actionsStyle}>
            <Link href="/logikality/accounts" style={secondaryBtnStyle}>
              Cancel
            </Link>
            <button
              type="submit"
              disabled={submitting}
              className="ol-new-account-btn"
              style={{
                ...primaryBtnStyle,
                opacity: submitting ? 0.7 : 1,
                cursor: submitting ? "wait" : "pointer",
              }}
            >
              {submitting ? "Creating…" : "Create account"}
            </button>
          </div>
          <style>{`
            .ol-new-account-btn { transition: background 0.15s; }
            .ol-new-account-btn:hover:not(:disabled) { background: ${chrome.amberDark}; }
          `}</style>
        </form>
      )}
    </div>
  );
}

function Field({
  label,
  htmlFor,
  required,
  children,
}: {
  label: string;
  htmlFor: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div style={fieldStyle}>
      <label htmlFor={htmlFor} style={labelStyle}>
        {label}
        {required ? <span style={{ color: chrome.amber }}> *</span> : null}
      </label>
      {children}
    </div>
  );
}

function SuccessPanel({
  created,
  copied,
  onCopy,
  onDone,
}: {
  created: CreateResponse;
  copied: boolean;
  onCopy: () => void;
  onDone: () => void;
}) {
  return (
    <div style={successCardStyle}>
      <div style={successBadgeStyle}>Account created</div>
      <h2 style={successTitleStyle}>{created.account.name}</h2>
      <dl style={dlStyle}>
        <dt style={dtStyle}>Customer portal</dt>
        <dd style={ddStyle}>
          <code style={codeStyle}>/{created.account.slug}</code>
        </dd>
        <dt style={dtStyle}>Primary admin</dt>
        <dd style={ddStyle}>{created.primary_admin_email}</dd>
        <dt style={dtStyle}>Temporary password</dt>
        <dd style={ddStyle}>
          <code style={{ ...codeStyle, marginRight: 8 }}>{created.temp_password}</code>
          <button type="button" onClick={onCopy} style={copyBtnStyle}>
            {copied ? "Copied" : "Copy"}
          </button>
        </dd>
      </dl>
      <p style={successNoteStyle}>
        This password is shown once and cannot be retrieved later. Share it
        securely — the admin should change it after first login.
      </p>
      <div style={actionsStyle}>
        <button type="button" onClick={onDone} style={primaryBtnStyle}>
          Done
        </button>
      </div>
    </div>
  );
}

/* ----- styles -------------------------------------------------------- */

const pageStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 20,
  maxWidth: 640,
};

const breadcrumbStyle: React.CSSProperties = {
  fontSize: 13,
};

const breadcrumbLinkStyle: React.CSSProperties = {
  color: chrome.mutedFg,
  textDecoration: "none",
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
};

const formStyle: React.CSSProperties = {
  backgroundColor: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 10,
  padding: 24,
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const fieldStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: typography.fontWeight.subheading,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: chrome.mutedFg,
};

const inputStyle: React.CSSProperties = {
  padding: "10px 12px",
  fontSize: 14,
  color: chrome.fg,
  backgroundColor: "#FFFFFF",
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  outline: "none",
  fontFamily: "inherit",
};

const actionsStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 10,
  marginTop: 4,
};

const primaryBtnStyle: React.CSSProperties = {
  backgroundColor: chrome.amber,
  color: "#FFFFFF",
  padding: "10px 18px",
  borderRadius: 8,
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  border: "none",
  textDecoration: "none",
  cursor: "pointer",
};

const secondaryBtnStyle: React.CSSProperties = {
  backgroundColor: "transparent",
  color: chrome.mutedFg,
  padding: "10px 18px",
  borderRadius: 8,
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  border: `1px solid ${chrome.border}`,
  textDecoration: "none",
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
};

const errorStyle: React.CSSProperties = {
  backgroundColor: "#FDECEC",
  color: "#8A1C1C",
  borderRadius: 8,
  padding: "10px 14px",
  fontSize: 14,
  lineHeight: 1.4,
};

const successCardStyle: React.CSSProperties = {
  backgroundColor: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 10,
  padding: 24,
  display: "flex",
  flexDirection: "column",
  gap: 14,
};

const successBadgeStyle: React.CSSProperties = {
  alignSelf: "flex-start",
  backgroundColor: chrome.amberBg,
  color: chrome.amberDark,
  padding: "4px 10px",
  borderRadius: 999,
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const successTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 20,
  fontWeight: typography.fontWeight.headline,
  color: chrome.charcoal,
};

const dlStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto 1fr",
  columnGap: 20,
  rowGap: 10,
  margin: 0,
  fontSize: 14,
};

const dtStyle: React.CSSProperties = {
  color: chrome.mutedFg,
  fontWeight: typography.fontWeight.subheading,
};

const ddStyle: React.CSSProperties = {
  margin: 0,
  color: chrome.fg,
  display: "flex",
  alignItems: "center",
};

const codeStyle: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 13,
  backgroundColor: chrome.muted,
  border: `1px solid ${chrome.border}`,
  padding: "3px 8px",
  borderRadius: 6,
  color: chrome.charcoal,
};

const copyBtnStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.amberDark,
  backgroundColor: "transparent",
  border: `1px solid ${chrome.border}`,
  borderRadius: 6,
  padding: "3px 10px",
  cursor: "pointer",
};

const successNoteStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  color: chrome.mutedFg,
  lineHeight: 1.5,
};
