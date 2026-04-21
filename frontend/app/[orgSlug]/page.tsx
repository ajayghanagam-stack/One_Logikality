"use client";

/**
 * Tenant landing — `/acme`, `/foo`, whatever the URL slug is.
 *
 *   - Unauthenticated visitor: render the login form (the tenant URL *is*
 *     the login surface, per the UX request).
 *   - Authenticated user whose own org_slug matches: render the customer
 *     home dashboard (the layout adds the sidebar chrome on top).
 *   - Authenticated user whose org_slug does NOT match: bounce them to
 *     their own `/{user.org_slug}`. Platform admins here get sent to
 *     `/logikality/accounts`.
 *
 * Deeper routes (e.g. `/acme/ecv`) use `useRequireRole(..., "/<slug>")`
 * so unauthenticated hits fall back to this login landing, not somewhere
 * else.
 */

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AuthBrandPanel } from "@/components/auth-brand-panel";
import { LoginForm } from "@/components/login-form";
import { chrome, typography } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

export default function TenantLanding() {
  const { user, hydrated } = useAuth();
  const params = useParams();
  const router = useRouter();
  const orgSlug = typeof params.orgSlug === "string" ? params.orgSlug : "";

  useEffect(() => {
    if (!hydrated || !user) return;
    if (user.role === "platform_admin") {
      router.replace("/logikality/accounts");
    } else if (user.org_slug && user.org_slug !== orgSlug) {
      router.replace(`/${user.org_slug}`);
    }
  }, [hydrated, user, orgSlug, router]);

  if (!hydrated) return null;

  const onOwnTenant =
    user &&
    (user.role === "customer_admin" || user.role === "customer_user") &&
    user.org_slug === orgSlug;

  if (onOwnTenant) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 720 }}>
        <h1
          style={{
            margin: 0,
            fontSize: 24,
            fontWeight: typography.fontWeight.headline,
            color: chrome.charcoal,
          }}
        >
          Welcome, {user.full_name.split(" ")[0]}.
        </h1>
        <p style={{ margin: 0, color: chrome.mutedFg, lineHeight: 1.5 }}>
          This is the customer portal home. Upload a packet, review ECV results, and
          configure rule sets from the sidebar. More surfaces land as later phases ship.
        </p>
      </div>
    );
  }

  // Either no user yet, or an authenticated user on the wrong tenant URL
  // (redirect is firing from the useEffect above). Show login in both
  // cases; the redirect will swap the page out shortly after.
  if (user) return null;

  return (
    <AuthBrandPanel>
      <LoginForm
        heading="Welcome back"
        subheading="Sign in to your organization to continue."
        allowedRoles={["customer_admin", "customer_user"]}
        destinationFor={(u) => `/${u.org_slug ?? ""}`}
      />
    </AuthBrandPanel>
  );
}
