"use client";

/**
 * Customer-admin Users page (US-2.2 / US-2.3 / US-2.4).
 *
 * Three concerns on one surface: invite form at top, temp-password banner
 * that appears after a successful invite (copy-to-clipboard), and the
 * Team members list with inline remove-with-confirm.
 *
 * Role enforcement: `useRequireRole("customer_admin")` is the UX guard;
 * the backend's `require_customer_admin` dep is the security boundary.
 * Customer users who land here via URL get bounced to `/{orgSlug}`.
 */

import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { useAuth, useRequireRole } from "@/lib/auth";
import { chrome, typography } from "@/lib/brand";

type WireRole = "admin" | "member";

type TeamMember = {
  id: string;
  email: string;
  full_name: string;
  role: WireRole;
  is_primary_admin: boolean;
  created_at: string;
};

type InviteResponse = {
  user: TeamMember;
  temp_password: string;
};

export default function TeamUsersPage() {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;
  const { ready } = useRequireRole(["customer_admin"], `/${orgSlug}`);
  const { token } = useAuth();

  const [members, setMembers] = useState<TeamMember[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Invite form state. Kept local here (not in a child) so a successful
  // invite can clear the inputs without a ref dance.
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WireRole>("member");
  const [submitting, setSubmitting] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [lastInvite, setLastInvite] = useState<InviteResponse | null>(null);
  const [copied, setCopied] = useState(false);

  // Per-row state for remove-with-confirm. A single id means that row is
  // currently asking for confirmation; another click anywhere else resets.
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    (async () => {
      try {
        const rows = await api<TeamMember[]>("/api/customer-admin/users", { token });
        if (!cancelled) setMembers(rows);
      } catch (err) {
        if (cancelled) return;
        const msg =
          err instanceof ApiError
            ? err.detail ?? `Request failed (${err.status}).`
            : "Could not load team members. Please try again.";
        setLoadError(msg);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token]);

  async function onInvite(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token) return;
    setSubmitting(true);
    setInviteError(null);
    setLastInvite(null);
    try {
      const resp = await api<InviteResponse>("/api/customer-admin/users", {
        method: "POST",
        token,
        json: { full_name: fullName.trim(), email: email.trim(), role },
      });
      setLastInvite(resp);
      setMembers((prev) => (prev ? [...prev, resp.user] : [resp.user]));
      setFullName("");
      setEmail("");
      setRole("member");
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not invite user. Please try again.";
      setInviteError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function onRemove(id: string) {
    if (!token) return;
    setRemoving(true);
    setRowError(null);
    try {
      await api<void>(`/api/customer-admin/users/${id}`, {
        method: "DELETE",
        token,
      });
      setMembers((prev) => prev?.filter((m) => m.id !== id) ?? null);
      setConfirmRemoveId(null);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail ?? `Request failed (${err.status}).`
          : "Could not remove user. Please try again.";
      setRowError(msg);
    } finally {
      setRemoving(false);
    }
  }

  async function copyPassword() {
    if (!lastInvite) return;
    await navigator.clipboard.writeText(lastInvite.temp_password);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  if (!ready) return null;

  return (
    <div style={pageStyle}>
      <nav style={breadcrumbStyle} aria-label="Breadcrumb">
        <span>Administration</span>
        <span style={breadcrumbSepStyle}>›</span>
        <span style={breadcrumbCurrentStyle}>Users</span>
      </nav>

      <header style={headerBlockStyle}>
        <h1 style={titleStyle}>Manage users</h1>
        <p style={subtitleStyle}>
          Invite team members to your organization. Admins can manage users
          and configuration; members can use the platform.
        </p>
      </header>

      <InviteCard
        fullName={fullName}
        email={email}
        role={role}
        submitting={submitting}
        error={inviteError}
        lastInvite={lastInvite}
        copied={copied}
        onNameChange={setFullName}
        onEmailChange={setEmail}
        onRoleChange={setRole}
        onSubmit={onInvite}
        onCopy={copyPassword}
      />

      <TeamList
        members={members}
        loadError={loadError}
        confirmRemoveId={confirmRemoveId}
        removing={removing}
        rowError={rowError}
        onAskConfirm={(id) => {
          setRowError(null);
          setConfirmRemoveId(id);
        }}
        onCancelConfirm={() => setConfirmRemoveId(null)}
        onConfirmRemove={onRemove}
      />
    </div>
  );
}

/* ----- invite card --------------------------------------------------- */

function InviteCard({
  fullName,
  email,
  role,
  submitting,
  error,
  lastInvite,
  copied,
  onNameChange,
  onEmailChange,
  onRoleChange,
  onSubmit,
  onCopy,
}: {
  fullName: string;
  email: string;
  role: WireRole;
  submitting: boolean;
  error: string | null;
  lastInvite: InviteResponse | null;
  copied: boolean;
  onNameChange: (v: string) => void;
  onEmailChange: (v: string) => void;
  onRoleChange: (v: WireRole) => void;
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  onCopy: () => void;
}) {
  const canSubmit = fullName.trim().length > 0 && email.trim().length > 0 && !submitting;
  return (
    <section style={cardStyle}>
      <div style={cardHeaderStyle}>
        <span style={{ fontSize: 15 }} aria-hidden="true">
          ✉️
        </span>
        <h3 style={cardTitleStyle}>Invite a user</h3>
      </div>
      <form onSubmit={onSubmit} style={formStyle} noValidate>
        <div style={formGridStyle}>
          <div>
            <label htmlFor="invite-name" style={labelStyle}>
              Full name
            </label>
            <input
              id="invite-name"
              type="text"
              value={fullName}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder="e.g. Pat Smith"
              required
              style={inputStyle}
            />
          </div>
          <div>
            <label htmlFor="invite-email" style={labelStyle}>
              Email
            </label>
            <input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => onEmailChange(e.target.value)}
              placeholder="pat.smith@acmemortgage.com"
              required
              style={inputStyle}
            />
          </div>
          <div>
            <label htmlFor="invite-role" style={labelStyle}>
              Role
            </label>
            <select
              id="invite-role"
              value={role}
              onChange={(e) => onRoleChange(e.target.value as WireRole)}
              style={{ ...inputStyle, cursor: "pointer" }}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={!canSubmit}
            style={{
              ...primaryBtnStyle,
              opacity: canSubmit ? 1 : 0.5,
              cursor: canSubmit ? "pointer" : "not-allowed",
            }}
          >
            {submitting ? "Inviting…" : "Invite user"}
          </button>
        </div>
      </form>

      {error ? (
        <div role="alert" style={formErrorStyle}>
          {error}
        </div>
      ) : null}

      {lastInvite ? (
        <div style={successBannerStyle} role="status">
          <div style={successHeaderStyle}>User invited successfully</div>
          <p style={successBodyStyle}>
            Share these credentials with{" "}
            <strong>{lastInvite.user.email}</strong> securely. They&rsquo;ll be
            asked to change the password on first login.
          </p>
          <div style={copyRowStyle}>
            <code style={passwordCodeStyle}>{lastInvite.temp_password}</code>
            <button
              type="button"
              onClick={onCopy}
              style={copyBtnStyle}
              title="Copy password"
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

/* ----- team list ----------------------------------------------------- */

function TeamList({
  members,
  loadError,
  confirmRemoveId,
  removing,
  rowError,
  onAskConfirm,
  onCancelConfirm,
  onConfirmRemove,
}: {
  members: TeamMember[] | null;
  loadError: string | null;
  confirmRemoveId: string | null;
  removing: boolean;
  rowError: string | null;
  onAskConfirm: (id: string) => void;
  onCancelConfirm: () => void;
  onConfirmRemove: (id: string) => void;
}) {
  const count = members?.length ?? 0;

  return (
    <section style={cardStyle}>
      <div style={cardHeaderStyle}>
        <span style={{ fontSize: 15 }} aria-hidden="true">
          👥
        </span>
        <h3 style={cardTitleStyle}>
          Team members{members ? ` (${count})` : ""}
        </h3>
      </div>

      {loadError ? (
        <div role="alert" style={formErrorStyle}>
          {loadError}
        </div>
      ) : null}
      {rowError ? (
        <div role="alert" style={formErrorStyle}>
          {rowError}
        </div>
      ) : null}

      <div>
        {members === null && !loadError ? (
          <div style={emptyRowStyle}>Loading team…</div>
        ) : null}
        {members && members.length === 0 ? (
          <div style={emptyRowStyle}>
            No users yet. Invite someone using the form above.
          </div>
        ) : null}
        {members?.map((user) => (
          <MemberRow
            key={user.id}
            user={user}
            confirming={confirmRemoveId === user.id}
            removing={removing && confirmRemoveId === user.id}
            onAskConfirm={() => onAskConfirm(user.id)}
            onCancelConfirm={onCancelConfirm}
            onConfirmRemove={() => onConfirmRemove(user.id)}
          />
        ))}
      </div>
    </section>
  );
}

function MemberRow({
  user,
  confirming,
  removing,
  onAskConfirm,
  onCancelConfirm,
  onConfirmRemove,
}: {
  user: TeamMember;
  confirming: boolean;
  removing: boolean;
  onAskConfirm: () => void;
  onCancelConfirm: () => void;
  onConfirmRemove: () => void;
}) {
  const initials =
    user.full_name
      .split(" ")
      .map((n) => n[0])
      .filter(Boolean)
      .join("")
      .slice(0, 2)
      .toUpperCase() || "?";

  return (
    <div style={memberRowStyle}>
      <div style={avatarStyle}>{initials}</div>
      <div style={{ flex: 1 }}>
        <div style={memberNameStyle}>{user.full_name}</div>
        <div style={memberEmailStyle}>{user.email}</div>
      </div>
      <span
        style={{
          ...rolePillStyle,
          background: user.role === "admin" ? chrome.amberBg : chrome.muted,
          borderColor: user.role === "admin" ? chrome.amberLight : chrome.border,
          color: user.role === "admin" ? chrome.amberDark : chrome.mutedFg,
        }}
      >
        {user.role}
      </span>
      {user.is_primary_admin ? (
        <span style={primaryPillStyle}>Primary</span>
      ) : confirming ? (
        <div style={{ display: "flex", gap: 5 }}>
          <button
            type="button"
            onClick={onConfirmRemove}
            disabled={removing}
            style={confirmBtnStyle}
          >
            {removing ? "…" : "Confirm"}
          </button>
          <button
            type="button"
            onClick={onCancelConfirm}
            disabled={removing}
            style={cancelBtnStyle}
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={onAskConfirm}
          title="Remove user"
          aria-label={`Remove ${user.full_name}`}
          className="ol-remove-user-btn"
          style={removeIconBtnStyle}
        >
          <TrashIcon />
        </button>
      )}
      <style>{`
        .ol-remove-user-btn { transition: background 0.15s, color 0.15s; }
        .ol-remove-user-btn:hover:not(:disabled) {
          background: #FEE2E2;
          color: #B91C1C;
        }
      `}</style>
    </div>
  );
}

function TrashIcon() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
    </svg>
  );
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

const headerBlockStyle: React.CSSProperties = {
  marginBottom: 4,
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

const cardHeaderStyle: React.CSSProperties = {
  padding: "14px 20px",
  borderBottom: `1px solid ${chrome.border}`,
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const cardTitleStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: typography.fontWeight.subheading,
  margin: 0,
  color: chrome.charcoal,
};

const formStyle: React.CSSProperties = {
  padding: "18px 22px",
};

const formGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr 140px auto",
  gap: 10,
  alignItems: "flex-end",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 10,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.mutedFg,
  letterSpacing: 0.4,
  textTransform: "uppercase",
  marginBottom: 5,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "9px 12px",
  fontSize: 13,
  border: `1px solid ${chrome.border}`,
  borderRadius: 8,
  background: chrome.card,
  color: chrome.charcoal,
  boxSizing: "border-box",
  fontFamily: typography.fontFamily.primary,
  outline: "none",
};

const primaryBtnStyle: React.CSSProperties = {
  padding: "10px 18px",
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  background: chrome.amber,
  color: "#fff",
  border: "none",
  borderRadius: 8,
  fontFamily: typography.fontFamily.primary,
  whiteSpace: "nowrap",
};

const formErrorStyle: React.CSSProperties = {
  margin: "0 22px 18px",
  background: "#FEE2E2",
  color: "#991B1B",
  border: "1px solid #FCA5A5",
  borderRadius: 8,
  padding: "8px 12px",
  fontSize: 12,
};

const successBannerStyle: React.CSSProperties = {
  margin: "0 22px 22px",
  padding: "14px 16px",
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  borderRadius: 9,
};

const successHeaderStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.amberDark,
  marginBottom: 8,
};

const successBodyStyle: React.CSSProperties = {
  fontSize: 12,
  color: chrome.amberDark,
  margin: "0 0 10px",
  lineHeight: 1.5,
};

const copyRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const passwordCodeStyle: React.CSSProperties = {
  flex: 1,
  padding: "9px 14px",
  background: "#fff",
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
  color: chrome.amberDark,
  border: `1px solid ${chrome.amberLight}`,
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const emptyRowStyle: React.CSSProperties = {
  padding: "40px 20px",
  textAlign: "center",
  color: chrome.mutedFg,
  fontSize: 13,
};

const memberRowStyle: React.CSSProperties = {
  padding: "14px 20px",
  borderBottom: `1px solid ${chrome.border}`,
  display: "flex",
  alignItems: "center",
  gap: 14,
};

const avatarStyle: React.CSSProperties = {
  width: 38,
  height: 38,
  borderRadius: "50%",
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
  color: chrome.amberDark,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
};

const memberNameStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  color: chrome.charcoal,
};

const memberEmailStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
  marginTop: 1,
};

const rolePillStyle: React.CSSProperties = {
  padding: "3px 10px",
  borderRadius: 12,
  border: "1px solid",
  fontSize: 10,
  fontWeight: typography.fontWeight.subheading,
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const primaryPillStyle: React.CSSProperties = {
  padding: "3px 10px",
  borderRadius: 12,
  background: "#EDE4F7",
  border: "1px solid #D4BEEE",
  fontSize: 10,
  fontWeight: typography.fontWeight.subheading,
  color: "#6B3FA0",
  letterSpacing: 0.4,
  textTransform: "uppercase",
};

const removeIconBtnStyle: React.CSSProperties = {
  width: 30,
  height: 30,
  borderRadius: 6,
  background: "transparent",
  border: "none",
  color: chrome.mutedFg,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontFamily: typography.fontFamily.primary,
};

const confirmBtnStyle: React.CSSProperties = {
  padding: "5px 10px",
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  background: "#DC2626",
  color: "#fff",
  border: "none",
  borderRadius: 5,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};

const cancelBtnStyle: React.CSSProperties = {
  padding: "5px 10px",
  fontSize: 11,
  fontWeight: typography.fontWeight.subheading,
  background: "#fff",
  color: chrome.mutedFg,
  border: `1px solid ${chrome.border}`,
  borderRadius: 5,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};
