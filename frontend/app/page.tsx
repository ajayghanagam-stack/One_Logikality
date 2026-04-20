"use client";

/**
 * Dual-portal login selector (US-1.1). Visitors pick Customer or Platform
 * Admin; each button routes to the corresponding login page. If the visitor
 * is already signed in (token + user in localStorage), we send them straight
 * to their portal without forcing a re-login.
 */

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { colors, logo, typography } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

export default function HomePage() {
  const { user, hydrated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!hydrated || !user) return;
    router.replace(user.role === "platform_admin" ? "/platform-admin/accounts" : "/customer");
  }, [hydrated, user, router]);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 40,
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

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          alignItems: "center",
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: 28,
            fontWeight: typography.fontWeight.headline,
            color: colors.charcoal,
            letterSpacing: "-0.01em",
          }}
        >
          Sign in to One Logikality
        </h1>
        <p style={{ margin: 0, color: colors.darkGray, fontSize: 15 }}>
          Choose the portal that matches your account.
        </p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: 16,
          width: "min(560px, 90vw)",
        }}
      >
        <PortalCard
          href="/customer/login"
          title="Customer"
          description="Mortgage lenders, servicers, title agencies, and BPOs."
        />
        <PortalCard
          href="/platform-admin/login"
          title="Platform admin"
          description="Logikality staff: manage customer accounts and subscriptions."
          tone="dark"
        />
      </div>
    </main>
  );
}

function PortalCard({
  href,
  title,
  description,
  tone = "light",
}: {
  href: string;
  title: string;
  description: string;
  tone?: "light" | "dark";
}) {
  const isDark = tone === "dark";
  return (
    <Link
      href={href}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 20,
        borderRadius: 10,
        border: isDark ? "none" : `1px solid ${colors.charcoal}22`,
        backgroundColor: isDark ? colors.charcoal : colors.white,
        color: isDark ? colors.white : colors.charcoal,
        textDecoration: "none",
        boxShadow: "0 1px 2px rgba(0,0,0,0.06)",
      }}
    >
      <div
        style={{
          fontSize: 18,
          fontWeight: typography.fontWeight.headline,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontSize: 14,
          color: isDark ? "rgba(255,255,255,0.75)" : colors.darkGray,
          lineHeight: 1.45,
        }}
      >
        {description}
      </div>
      <div
        style={{
          marginTop: "auto",
          color: isDark ? colors.teal : colors.teal,
          fontSize: 14,
          fontWeight: typography.fontWeight.subheading,
        }}
      >
        Sign in →
      </div>
    </Link>
  );
}
