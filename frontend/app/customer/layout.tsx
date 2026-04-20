"use client";

/**
 * Customer-portal layout. Guards /customer/** against non-customer roles
 * via `useRequireRole`, and renders the customer sidebar alongside the page.
 *
 * `/customer/login` is a sibling route (not nested under this layout) so the
 * login page doesn't get wrapped by the sidebar or guard — which would put
 * the visitor in a redirect loop before they even see the form.
 */

import { colors } from "@/lib/brand";
import { useRequireRole } from "@/lib/auth";
import { Sidebar } from "@/components/sidebar";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

export default function CustomerLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // Login lives at /customer/login — skip the guard so it can render.
  const isLoginRoute = pathname === "/customer/login";

  const { ready } = useRequireRole(
    ["customer_admin", "customer_user"],
    "/customer/login",
  );

  if (isLoginRoute) return <>{children}</>;
  if (!ready) return null;

  return (
    <div style={{ display: "flex", minHeight: "100vh", backgroundColor: "#F5F6F8" }}>
      <Sidebar />
      <section style={{ flex: 1, padding: 32, color: colors.charcoal }}>{children}</section>
    </div>
  );
}
