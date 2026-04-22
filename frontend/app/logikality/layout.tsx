"use client";

/**
 * Platform-admin portal chrome. `/logikality` itself is the login landing,
 * so the layout doesn't redirect-guard the index — it just decides whether
 * to wrap children in the sidebar + content chrome:
 *
 *   - Before hydration: render nothing (avoids flashing).
 *   - Authenticated platform admin: full chrome.
 *   - Anyone else: pass through to the child, which is either the login
 *     landing (`/logikality`) or a protected inner route (which handles
 *     its own redirect via `useRequireRole("/logikality")`).
 */

import type { ReactNode } from "react";

import { Sidebar } from "@/components/sidebar";
import { chrome } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

export default function PlatformAdminLayout({ children }: { children: ReactNode }) {
  const { user, hydrated } = useAuth();

  if (hydrated && user?.role === "platform_admin") {
    return (
      <div style={{ display: "flex", minHeight: "100vh", backgroundColor: chrome.bg }}>
        <Sidebar />
        <section style={{ flex: 1, padding: 32, color: chrome.charcoal }}>{children}</section>
      </div>
    );
  }

  return <>{children}</>;
}
