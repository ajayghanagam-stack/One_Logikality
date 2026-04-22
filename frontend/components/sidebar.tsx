"use client";

/**
 * Role-aware sidebar shell. Item list is derived from the signed-in user's
 * role (US-1.9): platform admins get the platform-admin nav; customer admins
 * get the full customer nav including Team + Configuration; customer users
 * get the customer nav minus the admin-only items.
 *
 * Visual design matches the `one-logikality-demo` sidebar (white surface,
 * amber active state, warm neutrals) so the production build reads as the
 * same family as the demo + Title Intelligence Hub. Colors come from the
 * `chrome` sub-palette in `lib/brand.ts`.
 */

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { chrome, logo, typography } from "@/lib/brand";
import { useAuth, type Role } from "@/lib/auth";
import { useLastPacketId } from "@/lib/last-packet";

type Item = { href: string; label: string; icon?: string; restoreLastPacket?: boolean };

type NavSection = { heading: string; items: Item[] };

/**
 * Build nav items. For customer roles, every URL is scoped to the user's
 * own `orgSlug` (e.g. `/acme/ecv`). Platform admin URLs live under the
 * reserved `/logikality/*` prefix.
 */
function sectionsFor(role: Role, orgSlug: string | null): NavSection[] {
  if (role === "platform_admin") {
    // Two sections mirror the demo: "Administration" for customer-facing
    // work, "Account" for the admin's own profile. Keeps the mental model
    // (what I manage vs. what's about me) visible at a glance.
    return [
      {
        heading: "Administration",
        items: [
          { href: "/logikality/accounts", label: "Customer accounts", icon: "🏢" },
        ],
      },
      {
        heading: "Account",
        items: [
          { href: "/logikality/profile", label: "Change password", icon: "🔑" },
        ],
      },
    ];
  }

  // Customer roles must have a slug; if somehow missing, fall through with
  // "#" placeholders — the layout guard will have already redirected by
  // the time this renders in practice.
  const base = orgSlug ? `/${orgSlug}` : "#";

  const sections: NavSection[] = [
    {
      heading: "Platform",
      items: [
        { href: base, label: "Home", icon: "🏠" },
        { href: `${base}/upload`, label: "Upload", icon: "⬆️" },
        {
          href: `${base}/ecv`,
          label: "ECV Dashboard",
          icon: "🔍",
          // Sidebar hydrates the URL with ?packet=<last-opened> when the
          // user has previously viewed a packet, so returning to the
          // dashboard from anywhere is one click instead of "Home → pick".
          restoreLastPacket: true,
        },
      ],
    },
  ];

  if (role === "customer_admin") {
    sections.push({
      heading: "Administration",
      items: [
        { href: `${base}/admin/users`, label: "Team", icon: "👥" },
        { href: `${base}/admin/apps`, label: "App access", icon: "🧩" },
        { href: `${base}/admin/configuration`, label: "Configuration", icon: "⚙️" },
        { href: `${base}/admin/profile`, label: "Change password", icon: "🔑" },
      ],
    });
  } else {
    sections.push({
      heading: "Account",
      items: [{ href: `${base}/profile`, label: "Profile", icon: "🔑" }],
    });
  }
  return sections;
}

export function Sidebar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  // Last packet the user opened on the ECV page, persisted by that page
  // on successful load. Subscribed so "ECV Dashboard" in the sidebar
  // deep-links straight back to it without a round-trip through Home.
  const lastPacketId = useLastPacketId(user?.org_slug);

  if (!user) return null;

  const sections = sectionsFor(user.role, user.org_slug);
  const identity = identityFor(user.role, user.full_name, user.email);
  const isCustomerAdmin = user.role === "customer_admin";
  const isPlatformAdmin = user.role === "platform_admin";

  return (
    <aside style={asideStyle}>
      {/* Logo */}
      <div style={logoBlockStyle}>
        <Image
          src={logo.withTaglinePng}
          alt="Logikality"
          width={140}
          height={38}
          priority
          style={{ width: 140, height: "auto" }}
        />
      </div>

      {/* Identity block — "Signed in as" for platform admin, "Organization"
          for customer roles. Label typography (10/0.5) is distinct from nav
          section headings (9/0.8) to match the demo. */}
      <div style={orgBlockStyle}>
        <div style={identityLabelStyle}>{identity.heading}</div>
        <div style={orgNameStyle}>{identity.primary}</div>
        {identity.secondary ? (
          <div style={identitySecondaryStyle}>{identity.secondary}</div>
        ) : null}
        {isCustomerAdmin ? <AdminBadge /> : null}
      </div>

      {/* Nav sections */}
      <nav style={navStyle} aria-label="Primary">
        {sections.map((section) => (
          <div key={section.heading} style={{ marginBottom: 8 }}>
            <div style={{ ...sectionLabelStyle, padding: "16px 20px 8px" }}>
              {section.heading}
            </div>
            {section.items.map((item) => {
              const active =
                pathname === item.href ||
                (pathname?.startsWith(item.href + "/") ?? false);
              // Opt-in per item (today: ECV Dashboard) — append the
              // stored packet id so the link re-opens the user's last
              // packet instead of the empty state.
              const href =
                item.restoreLastPacket && lastPacketId
                  ? `${item.href}?packet=${lastPacketId}`
                  : item.href;
              return (
                <Link
                  key={item.href}
                  href={href}
                  style={navItemStyle(active)}
                >
                  {item.icon ? (
                    <span style={{ fontSize: 14 }}>{item.icon}</span>
                  ) : null}
                  {item.label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Footer — platform admin's identity is already in the top block, so
          skip the repeating name/email there and use the demo's bordered
          "← Sign out" button. Customer roles keep the name/email footer. */}
      <div style={footerStyle}>
        {isPlatformAdmin ? null : (
          <div style={userBlockStyle}>
            <div style={userNameStyle}>{user.full_name}</div>
            <div style={userEmailStyle}>{user.email}</div>
          </div>
        )}
        <button
          type="button"
          onClick={logout}
          style={isPlatformAdmin ? platformSignOutButtonStyle : signOutButtonStyle}
        >
          {isPlatformAdmin ? "← Sign out" : "Sign out"}
        </button>
      </div>
    </aside>
  );
}

function AdminBadge() {
  return (
    <div style={adminBadgeStyle}>
      <svg
        width="9"
        height="9"
        viewBox="0 0 24 24"
        fill="none"
        stroke={chrome.amberDark}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
      <span style={adminBadgeTextStyle}>Admin mode</span>
    </div>
  );
}

function identityFor(
  role: Role,
  fullName: string,
  email: string,
): { heading: string; primary: string; secondary: string | null } {
  if (role === "platform_admin") {
    // Demo parity: fixed "Platform administrator" as primary, real email
    // underneath. Not a stealth display of user.full_name — every platform
    // admin in this model reads the same role label.
    return {
      heading: "Signed in as",
      primary: "Platform administrator",
      secondary: email,
    };
  }
  // Customer portal — the demo-seeded org is "Acme Mortgage Holdings".
  // Until we pipe the real org name through /auth/me, fall back to the
  // user's first name so the chrome is populated.
  return {
    heading: "Organization",
    primary: fullName.includes(" ") ? "Acme Mortgage Holdings" : fullName,
    secondary: null,
  };
}

/* ----- style objects ------------------------------------------------- */

const asideStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  width: 240,
  minHeight: "100vh",
  backgroundColor: chrome.card,
  borderRight: `1px solid ${chrome.border}`,
  position: "sticky",
  top: 0,
};

const logoBlockStyle: React.CSSProperties = {
  padding: "16px 20px",
  borderBottom: `1px solid ${chrome.border}`,
};

const orgBlockStyle: React.CSSProperties = {
  padding: "12px 20px",
  borderBottom: `1px solid ${chrome.border}`,
};

const sectionLabelStyle: React.CSSProperties = {
  fontSize: 9,
  fontWeight: 600,
  color: chrome.mutedFg,
  letterSpacing: 0.8,
  textTransform: "uppercase",
};

// Identity block uses a slightly larger label than nav section headings —
// matches the demo's 10px/0.5 spacing which gives the top block more
// visual weight than the subsequent nav groupings.
const identityLabelStyle: React.CSSProperties = {
  fontSize: 10,
  color: chrome.mutedFg,
  letterSpacing: 0.5,
  textTransform: "uppercase",
};

const identitySecondaryStyle: React.CSSProperties = {
  fontSize: 11,
  color: chrome.mutedFg,
  marginTop: 1,
};

const orgNameStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  marginTop: 2,
  color: chrome.charcoal,
};

const adminBadgeStyle: React.CSSProperties = {
  marginTop: 6,
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  padding: "2px 8px",
  borderRadius: 10,
  background: chrome.amberBg,
  border: `1px solid ${chrome.amberLight}`,
};

const adminBadgeTextStyle: React.CSSProperties = {
  fontSize: 9,
  fontWeight: 700,
  color: chrome.amberDark,
  letterSpacing: 0.6,
  textTransform: "uppercase",
};

const navStyle: React.CSSProperties = {
  flex: 1,
  padding: "8px 0",
  overflow: "auto",
};

function navItemStyle(active: boolean): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "8px 20px",
    fontSize: 13,
    fontWeight: active ? 600 : 400,
    color: active ? chrome.amber : chrome.charcoal,
    background: active ? chrome.amberBg : "transparent",
    borderLeft: active ? `3px solid ${chrome.amber}` : "3px solid transparent",
    textDecoration: "none",
    transition: "all 0.15s",
    fontFamily: typography.fontFamily.primary,
  };
}

const footerStyle: React.CSSProperties = {
  padding: "12px 20px",
  borderTop: `1px solid ${chrome.border}`,
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const userBlockStyle: React.CSSProperties = {
  fontSize: 12,
  lineHeight: 1.35,
};

const userNameStyle: React.CSSProperties = {
  fontWeight: 600,
  color: chrome.charcoal,
};

const userEmailStyle: React.CSSProperties = {
  color: chrome.mutedFg,
  fontSize: 11,
};

const signOutButtonStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 10px",
  fontSize: 10,
  background: "transparent",
  color: chrome.mutedFg,
  border: `1px solid ${chrome.border}`,
  borderRadius: 6,
  cursor: "pointer",
  letterSpacing: 0.4,
  textTransform: "uppercase",
  fontWeight: 500,
  fontFamily: typography.fontFamily.primary,
};

// Platform-admin variant — larger, mixed-case "← Sign out" with a leading
// arrow glyph, matching the demo's PlatformAdminSidebar exactly.
const platformSignOutButtonStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 12px",
  fontSize: 12,
  fontWeight: 500,
  background: "transparent",
  color: chrome.mutedFg,
  border: `1px solid ${chrome.border}`,
  borderRadius: 6,
  cursor: "pointer",
  fontFamily: typography.fontFamily.primary,
};
