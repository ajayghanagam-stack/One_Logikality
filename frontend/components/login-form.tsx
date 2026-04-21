"use client";

/**
 * Shared login form used by both portals. Parameterized by the heading,
 * submit button label, and the route to push on success. Both portals
 * POST the same /api/auth/login; which destination we navigate to after
 * a successful login depends on the returned role.
 *
 * Visual design mirrors Title Intelligence Hub: a soft white card with
 * shadow, "Welcome back" headline, label-above-input layout, primary CTA,
 * and a forgot-password affordance. Keeps the two Logikality products
 * visually consistent per CLAUDE.md.
 */

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { colors, typography } from "@/lib/brand";
import { ApiError, useAuth, type Role, type User } from "@/lib/auth";

type Props = {
  /** Card heading — typically "Welcome back". */
  heading?: string;
  /** Card subheading, e.g. "Sign in to continue". */
  subheading?: string;
  /** Submit button label. */
  submitLabel?: string;
  /** Roles allowed to sign in via this form. On success, if the returned
   * role isn't in this set, we reject rather than letting a customer into
   * the platform-admin portal or vice versa. */
  allowedRoles: Role[];
  /** Destination on successful login. Receives the full signed-in user so
   * customer pages can route to `/{user.org_slug}`. */
  destinationFor: (user: User) => string;
};

export function LoginForm({
  heading = "Welcome back",
  subheading,
  submitLabel = "Sign in",
  allowedRoles,
  destinationFor,
}: Props) {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user = await login(email, password);
      if (!allowedRoles.includes(user.role)) {
        setError("This sign-in is not valid for that account type.");
        return;
      }
      router.replace(destinationFor(user));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError(err.detail ?? "Invalid email or password.");
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={cardStyle}>
      <div style={cardHeaderStyle}>
        <h1 style={titleStyle}>{heading}</h1>
        {subheading ? <p style={subtitleStyle}>{subheading}</p> : null}
      </div>

      <form onSubmit={onSubmit} style={formStyle}>
        <div style={fieldStyle}>
          <label htmlFor="email" style={labelStyle}>
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
            placeholder="name@company.com"
            style={inputStyle}
          />
        </div>

        <div style={fieldStyle}>
          <div style={labelRowStyle}>
            <label htmlFor="password" style={labelStyle}>
              Password
            </label>
            <span style={forgotStyle} aria-disabled>
              Forgot password?
            </span>
          </div>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={submitting}
            placeholder="Enter your password"
            style={inputStyle}
          />
        </div>

        {error ? (
          <div role="alert" style={errorStyle}>
            {error}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className="ol-cta"
          style={{
            ...buttonStyle,
            cursor: submitting ? "not-allowed" : "pointer",
          }}
        >
          {submitting ? "Signing in…" : submitLabel}
        </button>
      </form>

      {/* TI Hub btn-cta parity: amber gradient + hover lift. Hover/disabled
          rules can't live in inline styles, so they ride along here. */}
      <style>{`
        .ol-cta {
          background: linear-gradient(135deg, oklch(0.750 0.170 65) 0%, oklch(0.680 0.190 55) 100%);
          box-shadow: 0 2px 8px rgba(0,0,0,0.12);
          transition: background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
        }
        .ol-cta:hover:not(:disabled) {
          background: linear-gradient(135deg, oklch(0.720 0.175 62) 0%, oklch(0.650 0.200 50) 100%);
          transform: translateY(-1px);
          box-shadow: 0 6px 20px oklch(0.750 0.170 65 / 0.30);
        }
        .ol-cta:active:not(:disabled) { transform: translateY(0); }
        .ol-cta:disabled { opacity: 0.5; box-shadow: none; transform: none; }
      `}</style>
    </div>
  );
}

/* ----- style objects ------------------------------------------------- */

const cardStyle: React.CSSProperties = {
  backgroundColor: colors.white,
  borderRadius: 14,
  padding: "28px 28px 32px",
  boxShadow:
    "0 10px 30px rgba(26,26,46,0.08), 0 2px 6px rgba(26,26,46,0.04)",
  border: "1px solid #EEF0F4",
};

const cardHeaderStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  paddingBottom: 16,
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 24,
  fontWeight: typography.fontWeight.headline,
  color: colors.charcoal,
  lineHeight: 1.2,
};

const subtitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 14,
  color: colors.darkGray,
  lineHeight: 1.5,
};

const formStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const fieldStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const labelRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
};

const labelStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  color: colors.charcoal,
};

const forgotStyle: React.CSSProperties = {
  fontSize: 12,
  color: colors.darkGray,
  opacity: 0.7,
};

const inputStyle: React.CSSProperties = {
  border: "1px solid #D6D8DD",
  borderRadius: 8,
  padding: "10px 12px",
  fontSize: 15,
  backgroundColor: colors.white,
  color: colors.charcoal,
  fontFamily: "inherit",
  outline: "none",
};

const errorStyle: React.CSSProperties = {
  backgroundColor: "#FDECEC",
  color: "#8A1C1C",
  borderRadius: 8,
  padding: "10px 12px",
  fontSize: 13,
  lineHeight: 1.4,
};

const buttonStyle: React.CSSProperties = {
  // background is set by the .ol-cta class (TI Hub amber gradient).
  color: colors.white,
  border: "none",
  borderRadius: 8,
  padding: "11px 16px",
  fontSize: 15,
  fontWeight: typography.fontWeight.subheading,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
  width: "100%",
};
