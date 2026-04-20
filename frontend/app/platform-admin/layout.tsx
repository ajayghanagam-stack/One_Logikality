"use client";

/**
 * Platform-admin portal layout. Guards /platform-admin/** against non-
 * platform roles. /platform-admin/login is a sibling that skips the guard
 * so the login form renders without a redirect loop.
 */

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Sidebar } from "@/components/sidebar";
import { colors } from "@/lib/brand";
import { useRequireRole } from "@/lib/auth";

export default function PlatformAdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isLoginRoute = pathname === "/platform-admin/login";

  const { ready } = useRequireRole(["platform_admin"], "/platform-admin/login");

  if (isLoginRoute) return <>{children}</>;
  if (!ready) return null;

  return (
    <div style={{ display: "flex", minHeight: "100vh", backgroundColor: "#F5F6F8" }}>
      <Sidebar />
      <section style={{ flex: 1, padding: 32, color: colors.charcoal }}>{children}</section>
    </div>
  );
}
