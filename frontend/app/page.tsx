"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";

export default function HomePage() {
  const { user, hydrated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!hydrated) return;
    if (user?.role === "platform_admin") {
      router.replace("/logikality/accounts");
    } else {
      router.replace("/logikality");
    }
  }, [hydrated, user, router]);

  return null;
}
