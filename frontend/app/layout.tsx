import type { Metadata } from "next";
import type { ReactNode } from "react";

import { colors, typography } from "@/lib/brand";

export const metadata: Metadata = {
  title: "One Logikality",
  description: "AI-powered mortgage document processing.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          backgroundColor: colors.white,
          color: colors.darkGray,
          fontFamily: typography.fontFamily.primary,
          fontWeight: typography.fontWeight.body,
        }}
      >
        {children}
      </body>
    </html>
  );
}
