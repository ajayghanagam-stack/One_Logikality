"use client";

/**
 * Platform-admin login landing.
 *
 * `/logikality` itself is the login surface: unauthenticated visitors see
 * the form, authenticated platform admins get redirected to
 * `/logikality/accounts`. Customer users who land here by mistake get
 * bounced to their own tenant home.
 *
 * The literal segment `logikality` is reserved by the DB (see migration
 * 0002 `orgs_slug_shape_check`), so it never collides with the dynamic
 * `/[orgSlug]/*` customer routes.
 */

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AuthBrandPanel } from "@/components/auth-brand-panel";
import { LoginForm } from "@/components/login-form";
import { useAuth } from "@/lib/auth";

export default function LogikalityLanding() {
  const { user, hydrated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!hydrated || !user) return;
    if (user.role === "platform_admin") {
      router.replace("/logikality/accounts");
    } else if (user.org_slug) {
      router.replace(`/${user.org_slug}`);
    }
  }, [hydrated, user, router]);

  if (hydrated && user) return null; // waiting on the redirect above

  return (
    <AuthBrandPanel>
      <LoginForm
        heading="Welcome back"
        subheading="Platform admin access — Logikality staff only."
        allowedRoles={["platform_admin"]}
        destinationFor={() => "/logikality/accounts"}
      />
    </AuthBrandPanel>
  );
}
