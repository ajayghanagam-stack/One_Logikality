"use client";

import { AuthBrandPanel } from "@/components/auth-brand-panel";
import { LoginForm } from "@/components/login-form";

export default function PlatformAdminLoginPage() {
  return (
    <AuthBrandPanel>
      <LoginForm
        heading="Welcome back"
        subheading="Platform admin access — Logikality staff only."
        allowedRoles={["platform_admin"]}
        destinationFor={() => "/platform-admin/accounts"}
      />
    </AuthBrandPanel>
  );
}
