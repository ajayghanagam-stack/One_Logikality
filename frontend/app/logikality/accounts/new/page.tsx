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
 * Visual layout mirrors `one-logikality-demo`'s
 * /platform-admin/accounts/new: breadcrumb, amber icon-tile header,
 * section-card panels, two-column grids, admin-typed password.
 *
 * DEMO AFFORDANCE — the platform admin types the customer admin's
 * initial password (min 6 chars), matching the demo. When the full
 * onboarding flow ships (email invite + forced first-login reset),
 * drop the password input and revert to the server's auto-generated
 * temp password. The backend accepts the empty case today so the
 * revert is a frontend-only change.
 *
 * Still missing vs. the demo: no subscribed-apps panel — subscription
 * persistence lands in US-2.5; showing it here would fake a save.
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

// Kept in lockstep with `ORG_TYPES` in backend/app/models.py — the `label`
// is what the API validates against. `desc` mirrors the demo's per-type
// caption shown under the select. If this list grows, surface it from the
// backend via a config endpoint rather than letting it drift further.
const ORG_TYPES = [
  { label: "Mortgage Lender", desc: "Origination, underwriting, closing" },
  { label: "Loan Servicer", desc: "Post-close, servicing, QC" },
  { label: "Title Agency", desc: "Title search, examination, closing" },
  { label: "Mortgage BPO", desc: "Outsourced operations and vendor services" },
] as const;

type OrgTypeLabel = (typeof ORG_TYPES)[number]["label"];

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
  const [type, setType] = useState<OrgTypeLabel>(ORG_TYPES[0].label);
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreateResponse | null>(null);
  const [copied, setCopied] = useState(false);

  if (!ready) return null;

  const canSubmit =
    name.trim().length > 0 &&
    adminName.trim().length > 0 &&
    adminEmail.trim().length > 0 &&
    adminPassword.length >= 6;

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token || !canSubmit) return;
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
          // Demo affordance — remove this key when reverting to
          // server-generated temp passwords (see page-level comment).
          initial_password: adminPassword,
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

  const selectedType = ORG_TYPES.find((t) => t.label === type);

  return (
    <div style={pageStyle}>
      <nav style={breadcrumbStyle} aria-label="Breadcrumb">
        <Link href="/logikality/accounts" style={breadcrumbLinkStyle}>
          Customer accounts
        </Link>
        <span style={breadcrumbSepStyle}>›</span>
        <span style={breadcrumbCurrentStyle}>Onboard new customer</span>
      </nav>

      <header style={headerStyle}>
        <div style={headerIconStyle} aria-hidden="true">
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
            <circle cx="8.5" cy="7" r="4" />
            <line x1="20" y1="8" x2="20" y2="14" />
            <line x1="23" y1="11" x2="17" y2="11" />
          </svg>
        </div>
        <div>
          <h1 style={titleStyle}>Onboard new customer</h1>
          <p style={subtitleStyle}>
            Create the organization and set the designated customer administrator.
          </p>
        </div>
      </header>

      {created ? (
        <SuccessCard
          created={created}
          copied={copied}
          onCopy={copyPassword}
          onDone={() => router.push("/logikality/accounts")}
        />
      ) : (
        <form onSubmit={onSubmit} style={formColumnStyle} noValidate>
          {/* ——— Organization details ——— */}
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>Organization details</h2>
            <div style={twoColGridStyle}>
              <Field label="Company name" htmlFor="org-name">
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
              <Field label="Organization type" htmlFor="org-type">
                <select
                  id="org-type"
                  value={type}
                  onChange={(e) => setType(e.target.value as OrgTypeLabel)}
                  required
                  style={{ ...inputStyle, cursor: "pointer" }}
                >
                  {ORG_TYPES.map((t) => (
                    <option key={t.label} value={t.label}>
                      {t.label}
                    </option>
                  ))}
                </select>
                {selectedType ? (
                  <div style={fieldHintStyle}>{selectedType.desc}.</div>
                ) : null}
              </Field>
            </div>
          </section>

          {/* ——— Designated customer administrator ——— */}
          <section style={sectionStyle}>
            <h2 style={sectionTitleStyle}>Designated customer administrator</h2>
            <p style={sectionIntroStyle}>
              The customer administrator can invite additional users, enable or disable
              subscribed micro-apps, and configure organization-level rule overrides.
            </p>
            <div style={twoColGridStyle}>
              <Field label="Admin full name" htmlFor="admin-name">
                <input
                  id="admin-name"
                  type="text"
                  value={adminName}
                  onChange={(e) => setAdminName(e.target.value)}
                  required
                  maxLength={120}
                  autoComplete="off"
                  style={inputStyle}
                  placeholder="Jane Smith"
                />
              </Field>
              <Field label="Admin email" htmlFor="admin-email">
                <input
                  id="admin-email"
                  type="email"
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                  required
                  autoComplete="off"
                  style={inputStyle}
                  placeholder="admin@acmemortgage.com"
                />
              </Field>
              {/* Full-width password input, matching the demo. `gridColumn:
                  1 / -1` spans both columns regardless of grid size so the
                  input shape matches the other inputs above. */}
              <div style={{ gridColumn: "1 / -1" }}>
                <Field label="Password (minimum 6 characters)" htmlFor="admin-password">
                  <input
                    id="admin-password"
                    type="password"
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    required
                    minLength={6}
                    maxLength={128}
                    autoComplete="new-password"
                    style={inputStyle}
                    placeholder="Set initial password"
                  />
                  <div style={fieldHintStyle}>
                    Share this password securely with the admin. They can change it
                    after signing in.
                  </div>
                </Field>
              </div>
            </div>
          </section>

          {/* Subscription management lands in US-2.5; flagging here so the
              scope of this page is obvious to whoever opens it next. */}
          <p style={phaseNoteStyle}>
            App subscriptions are configured after the account is created (US-2.5).
          </p>

          {error ? (
            <div role="alert" style={errorStyle}>
              {error}
            </div>
          ) : null}

          <div style={actionsStyle}>
            <Link href="/logikality/accounts" style={secondaryBtnStyle}>
              Back to accounts
            </Link>
            <button
              type="submit"
              disabled={submitting || !canSubmit}
              className="ol-create-btn"
              style={{
                ...primaryBtnStyle,
                opacity: submitting || !canSubmit ? 0.5 : 1,
                cursor: submitting || !canSubmit ? "not-allowed" : "pointer",
              }}
            >
              {submitting ? "Creating…" : "Create customer account"}
            </button>
          </div>
          <style>{`
            .ol-create-btn { transition: background 0.15s; }
            .ol-create-btn:hover:not(:disabled) { background: ${chrome.amberDark}; }
          `}</style>
        </form>
      )}
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
    <div style={fieldStyle}>
      <label htmlFor={htmlFor} style={labelStyle}>
        {label}
      </label>
      {children}
    </div>
  );
}

function SuccessCard({
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
    <div style={sectionStyle}>
      <div style={successBannerStyle}>
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="20 6 9 17 4 12" />
        </svg>
        <span>
          Account created for <strong>{created.account.name}</strong>.
        </span>
      </div>
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
      <p style={sectionIntroStyle}>
        This password is shown once and cannot be retrieved later. Share it securely
        — the admin should change it after first login.
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
  maxWidth: 760,
};

const breadcrumbStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  fontSize: 12,
  color: chrome.mutedFg,
};

const breadcrumbLinkStyle: React.CSSProperties = {
  color: chrome.amber,
  textDecoration: "none",
};

const breadcrumbSepStyle: React.CSSProperties = {
  color: chrome.mutedFg,
};

const breadcrumbCurrentStyle: React.CSSProperties = {
  color: chrome.charcoal,
  fontWeight: typography.fontWeight.subheading,
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
};

const headerIconStyle: React.CSSProperties = {
  width: 40,
  height: 40,
  borderRadius: 12,
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: chrome.amberDark,
  flexShrink: 0,
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 24,
  fontWeight: typography.fontWeight.headline,
  color: chrome.charcoal,
  letterSpacing: "-0.02em",
};

const subtitleStyle: React.CSSProperties = {
  margin: "2px 0 0",
  fontSize: 13,
  color: chrome.mutedFg,
  lineHeight: 1.5,
};

const formColumnStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 18,
};

const sectionStyle: React.CSSProperties = {
  backgroundColor: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 12,
  padding: "18px 22px",
  boxShadow: "0 1px 3px rgba(20,18,14,0.04)",
  display: "flex",
  flexDirection: "column",
  gap: 14,
};

const sectionTitleStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  margin: 0,
  color: chrome.charcoal,
};

const sectionIntroStyle: React.CSSProperties = {
  fontSize: 12,
  color: chrome.mutedFg,
  margin: 0,
  lineHeight: 1.5,
};

const twoColGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 14,
};

const fieldStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 500,
  color: chrome.charcoal,
};

const fieldHintStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
  lineHeight: 1.5,
  marginTop: 2,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  fontSize: 14,
  color: chrome.charcoal,
  backgroundColor: chrome.card,
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  outline: "none",
  fontFamily: "inherit",
  boxSizing: "border-box",
};

const phaseNoteStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 12,
  color: chrome.mutedFg,
  fontStyle: "italic",
};

const actionsStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 10,
};

const primaryBtnStyle: React.CSSProperties = {
  backgroundColor: chrome.amber,
  color: "#FFFFFF",
  padding: "10px 20px",
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
  backgroundColor: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  padding: "10px 14px",
  fontSize: 13,
  lineHeight: 1.4,
};

const successBannerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "10px 14px",
  background: "#D1FAE5",
  border: "1px solid #A7F3D0",
  borderRadius: 8,
  fontSize: 13,
  color: "#065F46",
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
