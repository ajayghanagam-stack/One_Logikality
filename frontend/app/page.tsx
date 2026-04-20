import Image from "next/image";

import { colors, logo, typography } from "@/lib/brand";

/**
 * Phase 0 landing page. Renders the approved Logikality wordmark and brand
 * palette. Real dual-portal login selector lands in Step 1 (Phase 1, US-1.1).
 */
export default function HomePage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 32,
        padding: 48,
      }}
    >
      <Image
        src={logo.withTaglinePng}
        alt="Logikality — Intelligence. Decided."
        width={320}
        height={120}
        priority
        style={{ width: "min(320px, 60vw)", height: "auto" }}
      />

      <h1
        style={{
          margin: 0,
          fontSize: 28,
          fontWeight: typography.fontWeight.headline,
          color: colors.charcoal,
          letterSpacing: "-0.01em",
        }}
      >
        One Logikality
      </h1>

      <p style={{ margin: 0, maxWidth: 520, textAlign: "center", lineHeight: 1.5 }}>
        Multi-tenant platform for AI-powered mortgage document processing. Phase 0
        scaffold — dual-portal login selector lands in Phase 1.
      </p>

      {/* Brand palette swatches — confirm tokens match the PDF on first paint. */}
      <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
        {(
          [
            { name: "Teal", value: colors.teal },
            { name: "Purple", value: colors.purple },
            { name: "Orange", value: colors.orange },
            { name: "Charcoal", value: colors.charcoal },
          ] as const
        ).map((swatch) => (
          <div
            key={swatch.name}
            style={{
              width: 64,
              height: 64,
              borderRadius: 8,
              backgroundColor: swatch.value,
              boxShadow: "0 1px 2px rgba(0,0,0,0.08)",
            }}
            title={`${swatch.name} ${swatch.value}`}
          />
        ))}
      </div>
    </main>
  );
}
