"use client";

/**
 * Role-aware sidebar shell. The item list is derived from the signed-in
 * user's role (US-1.9): platform admins get the platform-admin nav; customer
 * admins get the full customer nav including Team + Configuration; customer
 * users get the customer nav minus the admin-only items.
 *
 * Kept deliberately simple for Step 1 — most of these routes don't exist
 * yet. Later phases add ECV, the micro-apps, and the admin surfaces; new
 * items slot into the existing `itemsFor(role)` switch.
 */

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { colors, logo, typography } from "@/lib/brand";
import { useAuth, type Role } from "@/lib/auth";

type Item = { href: string; label: string };

function itemsFor(role: Role, isPrimaryAdmin: boolean): Item[] {
  if (role === "platform_admin") {
    return [
      { href: "/platform-admin/accounts", label: "Accounts" },
      { href: "/platform-admin/profile", label: "Profile" },
    ];
  }
  // Customer portal: base items for every customer user, plus admin-only
  // surfaces guarded by role === 'customer_admin' (not is_primary_admin —
  // any customer admin can manage team/config; primary-protection only
  // affects removal per US-2.4).
  const base: Item[] = [
    { href: "/customer", label: "Home" },
    { href: "/customer/ecv", label: "ECV" },
  ];
  if (role === "customer_admin") {
    base.push(
      { href: "/customer/admin/users", label: "Team" },
      { href: "/customer/admin/apps", label: "App access" },
      { href: "/customer/admin/configuration", label: "Configuration" },
      { href: "/customer/admin/profile", label: "Profile" },
    );
  } else {
    base.push({ href: "/customer/profile", label: "Profile" });
  }
  // Suppress unused-param warning until is_primary_admin gates something.
  void isPrimaryAdmin;
  return base;
}

export function Sidebar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  if (!user) return null;

  const items = itemsFor(user.role, user.is_primary_admin);

  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        width: 240,
        minHeight: "100vh",
        backgroundColor: colors.charcoal,
        color: colors.white,
        padding: "24px 16px",
        boxSizing: "border-box",
      }}
    >
      <Link href="/" style={{ display: "block", marginBottom: 24 }}>
        <Image
          src={logo.reverseNoTagline}
          alt="Logikality"
          width={160}
          height={36}
          priority
          style={{ width: 160, height: "auto" }}
        />
      </Link>

      <nav
        style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1 }}
        aria-label="Primary"
      >
        {items.map((item) => {
          const active = pathname === item.href || pathname?.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              style={{
                display: "block",
                padding: "8px 12px",
                borderRadius: 6,
                color: active ? colors.white : "rgba(255,255,255,0.75)",
                backgroundColor: active ? "rgba(1,186,237,0.18)" : "transparent",
                textDecoration: "none",
                fontSize: 14,
                fontWeight: active
                  ? typography.fontWeight.subheading
                  : typography.fontWeight.body,
              }}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div
        style={{
          borderTop: "1px solid rgba(255,255,255,0.12)",
          paddingTop: 16,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <div style={{ fontSize: 13, lineHeight: 1.35 }}>
          <div style={{ fontWeight: typography.fontWeight.subheading }}>{user.full_name}</div>
          <div style={{ color: "rgba(255,255,255,0.6)" }}>{user.email}</div>
          <div style={{ color: "rgba(255,255,255,0.45)", fontSize: 12, marginTop: 2 }}>
            {roleLabel(user.role)}
          </div>
        </div>
        <button
          type="button"
          onClick={logout}
          style={{
            backgroundColor: "transparent",
            color: colors.white,
            border: "1px solid rgba(255,255,255,0.24)",
            borderRadius: 6,
            padding: "6px 10px",
            fontSize: 13,
            fontFamily: "inherit",
            cursor: "pointer",
          }}
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}

function roleLabel(role: Role): string {
  switch (role) {
    case "platform_admin":
      return "Platform admin";
    case "customer_admin":
      return "Customer admin";
    case "customer_user":
      return "Customer user";
  }
}
