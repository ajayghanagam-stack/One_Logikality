"use client";

import { chrome, typography } from "@/lib/brand";
import { useRequireRole } from "@/lib/auth";

export default function AccountsPage() {
  // Protected route — unauth visitors get bounced to `/logikality`, which
  // *is* the platform-admin login landing.
  const { ready } = useRequireRole(["platform_admin"], "/logikality");
  if (!ready) return null;

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
        Customer accounts
      </h1>
      <p style={{ margin: 0, color: chrome.mutedFg, lineHeight: 1.5 }}>
        Step 2 lands the accounts list, KPIs, and CRUD (US-1.5 – 1.7). This page is
        a placeholder so platform-admin login has somewhere to land.
      </p>
    </div>
  );
}
