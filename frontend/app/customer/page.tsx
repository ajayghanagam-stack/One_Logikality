"use client";

import { colors, typography } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

export default function CustomerHomePage() {
  const { user } = useAuth();
  if (!user) return null;

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
        Welcome, {user.full_name.split(" ")[0]}.
      </h1>
      <p style={{ margin: 0, color: colors.darkGray, lineHeight: 1.5 }}>
        This is the customer portal home. Upload a packet, review ECV results, and
        configure rule sets from the sidebar. More surfaces land as later phases ship.
      </p>
    </div>
  );
}
