"use client";

/**
 * Shared login form used by both portals. Parameterized by the heading,
 * submit button label, and the route to push on success. Both portals
 * POST the same /api/auth/login; which destination we navigate to after
 * a successful login depends on the returned role.
 */

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { colors, typography } from "@/lib/brand";
import { ApiError, useAuth, type Role } from "@/lib/auth";

type Props = {
  /** Heading above the form, e.g. "Customer sign-in". */
  heading: string;
  /** Subtext shown under the heading. */
  subheading?: string;
  /** Submit button label. */
  submitLabel?: string;
  /** Roles allowed to sign in via this form. On success, if the returned
   * role isn't in this set, we reject rather than letting a customer into
   * the platform-admin portal or vice versa. */
  allowedRoles: Role[];
  /** Destination on successful login (keyed off returned role). */
  destinationFor: (role: Role) => string;
};

export function LoginForm({
  heading,
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
      router.replace(destinationFor(user.role));
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
    <form
      onSubmit={onSubmit}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        width: "100%",
        maxWidth: 360,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <h1
          style={{
            margin: 0,
            fontSize: 24,
            fontWeight: typography.fontWeight.headline,
            color: colors.charcoal,
          }}
        >
          {heading}
        </h1>
        {subheading ? (
          <p style={{ margin: 0, color: colors.darkGray, fontSize: 14 }}>{subheading}</p>
        ) : null}
      </div>

      <label style={labelStyle}>
        <span style={labelTextStyle}>Email</span>
        <input
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={submitting}
          style={inputStyle}
        />
      </label>

      <label style={labelStyle}>
        <span style={labelTextStyle}>Password</span>
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={submitting}
          style={inputStyle}
        />
      </label>

      {error ? (
        <div
          role="alert"
          style={{
            backgroundColor: "#FDECEC",
            color: "#8A1C1C",
            borderRadius: 6,
            padding: "8px 12px",
            fontSize: 14,
          }}
        >
          {error}
        </div>
      ) : null}

      <button
        type="submit"
        disabled={submitting}
        style={{
          backgroundColor: colors.teal,
          color: colors.white,
          border: "none",
          borderRadius: 6,
          padding: "10px 16px",
          fontSize: 15,
          fontWeight: typography.fontWeight.subheading,
          cursor: submitting ? "not-allowed" : "pointer",
          opacity: submitting ? 0.7 : 1,
        }}
      >
        {submitting ? "Signing in…" : submitLabel}
      </button>
    </form>
  );
}

const labelStyle = {
  display: "flex",
  flexDirection: "column" as const,
  gap: 4,
};
const labelTextStyle = {
  fontSize: 13,
  fontWeight: typography.fontWeight.subheading,
  color: colors.darkGray,
};
const inputStyle = {
  border: `1px solid #D6D8DD`,
  borderRadius: 6,
  padding: "9px 12px",
  fontSize: 15,
  backgroundColor: colors.white,
  color: colors.charcoal,
  fontFamily: "inherit",
};
