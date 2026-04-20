"use client";

import { colors, typography } from "@/lib/brand";

export default function AccountsPage() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 720 }}>
      <h1
        style={{
          margin: 0,
          fontSize: 24,
          fontWeight: typography.fontWeight.headline,
          color: colors.charcoal,
        }}
      >
        Customer accounts
      </h1>
      <p style={{ margin: 0, color: colors.darkGray, lineHeight: 1.5 }}>
        Step 2 lands the accounts list, KPIs, and CRUD (US-1.5 – 1.7). This page is
        a placeholder so platform-admin login has somewhere to land.
      </p>
    </div>
  );
}
