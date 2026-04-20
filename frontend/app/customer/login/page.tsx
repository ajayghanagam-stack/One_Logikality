"use client";

import { AuthBrandPanel } from "@/components/auth-brand-panel";
import { LoginForm } from "@/components/login-form";

export default function CustomerLoginPage() {
  return (
    <AuthBrandPanel>
      <LoginForm
        heading="Welcome back"
        subheading="Sign in to your organization to continue."
        allowedRoles={["customer_admin", "customer_user"]}
        destinationFor={() => "/customer"}
      />
    </AuthBrandPanel>
  );
}
