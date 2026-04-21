/**
 * Logikality brand tokens.
 *
 * Authoritative source: docs/Logikality_Brand_Guidelines.pdf.
 * This file MUST stay in sync with the PDF — if there is a conflict, the PDF wins.
 * All color/typography/logo usage in the app flows through these exports;
 * no raw hex literals or ad-hoc logo paths elsewhere.
 */

export const colors = {
  // Primary palette
  teal: "#01BAED",      // primary brand, CTAs
  purple: "#BD33A4",    // accents, highlights
  orange: "#FCAE1E",    // emphasis, alerts

  // Secondary palette
  charcoal: "#1A1A2E",  // backgrounds, text (headline color on light surfaces)
  darkGray: "#53585F",  // body text
  white: "#FFFFFF",     // backgrounds, contrast
} as const;

export type ColorToken = keyof typeof colors;

export const typography = {
  /**
   * Primary typeface is Proxima Nova (Adobe Fonts / commercial licence). Until
   * the Typekit kit is wired into _document, the fallback stack renders —
   * which is still on-brand per the PDF.
   */
  fontFamily: {
    primary: `"Proxima Nova", Arial, Helvetica, sans-serif`,
  },
  fontWeight: {
    headline: 800,     // Extrabold
    subheading: 700,   // Bold
    body: 400,         // Regular
  },
} as const;

/**
 * Secondary chrome palette — warm neutrals + amber accent used by layout
 * surfaces (sidebars, page backgrounds, nav active states, callouts).
 *
 * Derived from the Title Intelligence Hub visual system (same values as the
 * one-logikality-demo `BRAND` export) so the two Logikality products read
 * as one family per CLAUDE.md. The primary palette above remains the
 * PDF-authoritative brand marks; these are strictly surface tokens.
 */
export const chrome = {
  // Surfaces
  bg: "#FAFAF8",          // page background
  card: "#FEFEFE",        // elevated card surface
  muted: "#F5F5F2",       // subtle fill

  // Borders
  border: "#E8E4DC",
  borderHover: "#D1CBBE",

  // Warm text — darker + more neutral than pure brand charcoal
  fg: "#1A1714",
  charcoal: "#2B2622",
  mutedFg: "#7A7468",

  // Amber accent for active nav, warnings, callouts
  amber: "#D4930F",
  amberDark: "#C07B10",
  amberLight: "#F5E6C8",
  amberBg: "#FDF6E9",
} as const;

/**
 * Approved Logikality logo assets under /public/.
 * Per CLAUDE.md: never recreate, re-trace, or inline-SVG the mark — reference
 * these files only.
 */
export const logo = {
  /** Primary — reversed, no tagline. For dark backgrounds. */
  reverseNoTagline: "/Logo_rev_no-tagline.svg",
  /** Secondary — full wordmark with tagline. For light backgrounds. */
  withTagline: "/Logo_withTagline.svg",
  /** Raster variants (use next/image for Proxima-rendered wordmark). */
  withTaglinePng: "/logikality_with_tagline.png",
  basePng: "/logikality_logo.png",
  websitePng: "/logikality_website.png",
  /** Minimum width per brand guidelines. */
  minWidthPx: 100,
} as const;
