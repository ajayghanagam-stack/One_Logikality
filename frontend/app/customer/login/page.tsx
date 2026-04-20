"use client";

import Image from "next/image";

import { LoginForm } from "@/components/login-form";
import { colors, logo } from "@/lib/brand";

export default function CustomerLoginPage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 48,
        backgroundColor: colors.white,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 32,
          width: "100%",
          maxWidth: 400,
        }}
      >
        <Image
          src={logo.withTaglinePng}
          alt="Logikality"
          width={240}
          height={90}
          priority
          style={{ width: 240, height: "auto" }}
        />
        <LoginForm
          heading="Customer sign-in"
          subheading="Use your organization email and password."
          allowedRoles={["customer_admin", "customer_user"]}
          destinationFor={() => "/customer"}
        />
      </div>
    </main>
  );
}
