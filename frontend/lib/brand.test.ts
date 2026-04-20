import { describe, expect, it } from "vitest";

import { colors, logo, typography } from "./brand";

/**
 * Anchor tokens to the brand guidelines PDF. If any of these fail, the PDF
 * has changed (or someone edited lib/brand.ts without updating the PDF) and
 * the palette is out of sync. See docs/Logikality_Brand_Guidelines.pdf.
 */
describe("brand tokens", () => {
  it("primary palette matches the PDF", () => {
    expect(colors.teal).toBe("#01BAED");
    expect(colors.purple).toBe("#BD33A4");
    expect(colors.orange).toBe("#FCAE1E");
  });

  it("secondary palette matches the PDF", () => {
    expect(colors.charcoal).toBe("#1A1A2E");
    expect(colors.darkGray).toBe("#53585F");
    expect(colors.white).toBe("#FFFFFF");
  });

  it("typography names Proxima Nova as primary", () => {
    expect(typography.fontFamily.primary).toContain("Proxima Nova");
    expect(typography.fontWeight.headline).toBe(800);
  });

  it("logo paths reference approved asset files only", () => {
    for (const path of Object.values(logo)) {
      if (typeof path === "string") {
        expect(path.startsWith("/")).toBe(true);
      }
    }
    expect(logo.minWidthPx).toBe(100);
  });
});
