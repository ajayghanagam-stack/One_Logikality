"use client";

/**
 * Tenant chrome. `/${orgSlug}` itself is the login landing, so the layout
 * doesn't redirect-guard the index — it just decides whether to wrap
 * children in the sidebar + content chrome:
 *
 *   - Before hydration: render nothing.
 *   - Authenticated customer on their own tenant URL: full chrome.
 *   - Anyone else: pass through. The child route decides whether to show
 *     the login form (`/[orgSlug]` index) or bounce to somewhere else
 *     (`useRequireRole` in any protected inner route).
 *
 * Server-side tenant isolation is enforced by Postgres RLS regardless of
 * what the layout paints — this is a friendly UX check, not a security
 * boundary.
 */

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { Sidebar } from "@/components/sidebar";
import { chrome } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

export default function TenantLayout({ children }: { children: ReactNode }) {
  const { user, hydrated } = useAuth();
  const params = useParams();
  const orgSlug = typeof params.orgSlug === "string" ? params.orgSlug : "";

  if (!hydrated) return null;

  const onOwnTenant =
    user &&
    (user.role === "customer_admin" || user.role === "customer_user") &&
    user.org_slug === orgSlug;

  if (onOwnTenant) {
    return (
      <div style={{ display: "flex", minHeight: "100vh", backgroundColor: chrome.bg }}>
        <Sidebar />
        <section style={{ flex: 1, padding: 32, color: chrome.charcoal }}>{children}</section>
      </div>
    );
  }

  return <>{children}</>;
}
