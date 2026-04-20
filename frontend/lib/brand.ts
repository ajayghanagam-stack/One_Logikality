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
