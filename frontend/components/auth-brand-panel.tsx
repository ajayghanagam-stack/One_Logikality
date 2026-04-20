"use client";

/**
 * Split-screen auth layout used by both portals. Mirrors the Title
 * Intelligence Hub login chrome so the two Logikality products feel like
 * one family: left panel is the gradient brand panel (hidden on mobile);
 * right panel hosts the form card.
 *
 * Pure inline styles + brand tokens per CLAUDE.md — no CSS files, no
 * Tailwind. The decorative pulse-glow animation is injected via a <style>
 * tag because keyframes can't live in inline-style objects.
 */

import Image from "next/image";
import type { ReactNode } from "react";

import { colors, logo, typography } from "@/lib/brand";

type Props = {
  /** Right-panel body — the form card, injected by the login page. */
  children: ReactNode;
};

export function AuthBrandPanel({ children }: Props) {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      {/* LEFT — branded gradient panel (desktop only) */}
      <div className="ol-auth-left" style={leftPanelStyle}>
        {/* Pulse glow */}
        <div style={glowWrapperStyle} aria-hidden>
          <div className="ol-auth-pulse" style={glowCircleStyle} />
        </div>

        {/* Decorative rings */}
        <div style={ringStyle(560, 0.18)} aria-hidden />
        <div style={ringStyle(700, 0.1)} aria-hidden />

        {/* Corner glows */}
        <div style={cornerGlow("top-left")} aria-hidden />
        <div style={cornerGlow("bottom-right")} aria-hidden />

        {/* Right-edge accent */}
        <div style={rightEdgeAccent} aria-hidden />

        {/* Content */}
        <div style={contentStackStyle}>
          {/* Logo card — white card on gradient */}
          <div style={logoCardStyle}>
            <Image
              src={logo.withTagline}
              alt="Logikality"
              width={240}
              height={65}
              priority
              style={{ width: "auto", height: "auto", maxWidth: 240 }}
            />
          </div>

          {/* Tagline block */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
            <p style={taglineStyle}>Decision-ready AI for mortgage operations</p>
            <div style={taglineRuleStyle} />
            <p style={trustLineStyle}>Trusted by mortgage professionals</p>
          </div>
        </div>
      </div>

      {/* RIGHT — form panel */}
      <div style={rightPanelStyle}>
        <div style={{ width: "100%", maxWidth: 420 }}>
          {/* Brand logo above the form */}
          <div style={{ marginBottom: 24, display: "flex", justifyContent: "center" }}>
            <Image
              src={logo.withTagline}
              alt="Logikality"
              width={160}
              height={44}
              priority
              style={{ width: "auto", height: "auto", maxWidth: 160 }}
            />
          </div>

          {children}

          <p style={poweredByStyle}>Powered by Logikality</p>
        </div>
      </div>

      {/* Global keyframes + responsive hide — the only non-inline bit we need. */}
      <style>{`
        @keyframes olAuthPulse {
          0%, 100% { opacity: 0.7; transform: scale(1); }
          50%      { opacity: 1;   transform: scale(1.08); }
        }
        .ol-auth-pulse { animation: olAuthPulse 4s ease-in-out infinite; }
        @media (max-width: 1023px) {
          .ol-auth-left { display: none !important; }
        }
      `}</style>
    </div>
  );
}

/* ----- style objects ------------------------------------------------- */

const leftPanelStyle: React.CSSProperties = {
  flex: "0 0 50%",
  position: "relative",
  overflow: "hidden",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  // Exact TI Hub gradient (oklch) so the two products read as one family.
  background:
    "linear-gradient(135deg, oklch(0.800 0.117 65) 0%, oklch(0.745 0.131 55) 100%)",
};

const rightPanelStyle: React.CSSProperties = {
  flex: 1,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  backgroundColor: colors.white,
  padding: "48px 24px",
};

const glowWrapperStyle: React.CSSProperties = {
  position: "absolute",
  inset: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  pointerEvents: "none",
};

const glowCircleStyle: React.CSSProperties = {
  width: 420,
  height: 420,
  borderRadius: "50%",
  background:
    "radial-gradient(circle, rgba(255,255,255,0.18) 0%, transparent 70%)",
};

function ringStyle(size: number, alpha: number): React.CSSProperties {
  return {
    position: "absolute",
    width: size,
    height: size,
    borderRadius: "50%",
    border: `1px solid rgba(255,255,255,${alpha})`,
    top: "50%",
    left: "50%",
    transform: "translate(-50%, -50%)",
    pointerEvents: "none",
  };
}

function cornerGlow(pos: "top-left" | "bottom-right"): React.CSSProperties {
  const base: React.CSSProperties = {
    position: "absolute",
    borderRadius: "50%",
    pointerEvents: "none",
  };
  if (pos === "top-left") {
    return {
      ...base,
      top: -80,
      left: -80,
      width: 320,
      height: 320,
      background:
        "radial-gradient(circle, rgba(255,255,255,0.15) 0%, transparent 70%)",
    };
  }
  return {
    ...base,
    bottom: -80,
    right: -48,
    width: 288,
    height: 288,
    background: "radial-gradient(circle, rgba(0,0,0,0.08) 0%, transparent 70%)",
  };
}

const rightEdgeAccent: React.CSSProperties = {
  position: "absolute",
  right: 0,
  top: 0,
  bottom: 0,
  width: 1,
  background:
    "linear-gradient(to bottom, transparent 0%, rgba(255,255,255,0.30) 50%, transparent 100%)",
  pointerEvents: "none",
};

const contentStackStyle: React.CSSProperties = {
  position: "relative",
  zIndex: 1,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 32,
  padding: "0 64px",
  textAlign: "center",
  width: "100%",
  maxWidth: 420,
};

const logoCardStyle: React.CSSProperties = {
  width: "100%",
  borderRadius: 24,
  backgroundColor: colors.white,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  padding: "40px 40px",
  boxShadow:
    "0 8px 40px rgba(0,0,0,0.20), 0 2px 12px rgba(0,0,0,0.10)",
  border: "1px solid rgba(255,255,255,0.60)",
};

const taglineStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 16,
  fontWeight: typography.fontWeight.subheading,
  color: "rgba(255,255,255,0.90)",
  lineHeight: 1.6,
  letterSpacing: "0.02em",
};

const taglineRuleStyle: React.CSSProperties = {
  width: 64,
  height: 2,
  borderRadius: 999,
  backgroundColor: "rgba(255,255,255,0.40)",
};

const trustLineStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 12,
  color: "rgba(255,255,255,0.60)",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
};

const poweredByStyle: React.CSSProperties = {
  margin: "24px 0 0",
  textAlign: "center",
  fontSize: 12,
  color: colors.darkGray,
  opacity: 0.7,
};
