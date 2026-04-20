"use client";

/**
 * Client-side auth state.
 *
 * Token + user are persisted to localStorage (`ol_auth_v1`) so a page
 * refresh doesn't bounce the user back to the portal selector. This is a
 * demo-grade pattern: XSS-exposed, no refresh tokens, no silent refresh.
 * Production auth will replace this whole module — don't build on it.
 *
 * `requireRole` is a small client-side guard that redirects if the user
 * isn't logged in as one of the allowed roles. It is NOT a security
 * boundary — every protected endpoint must still check auth server-side.
 */

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api, ApiError } from "./api";

export type Role = "platform_admin" | "customer_admin" | "customer_user";

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  org_id: string | null;
  is_primary_admin: boolean;
};

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

type AuthState = {
  user: User | null;
  token: string | null;
  /** True until localStorage has been checked on first mount (prevents a
   * one-frame "logged out" flash on guarded pages after a refresh). */
  hydrated: boolean;
  login(email: string, password: string): Promise<User>;
  logout(): void;
};

const STORAGE_KEY = "ol_auth_v1";

const AuthContext = createContext<AuthState | null>(null);

type Persisted = { token: string; user: User };

function readPersisted(): Persisted | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as Persisted;
  } catch {
    return null;
  }
}

function writePersisted(value: Persisted | null): void {
  if (typeof window === "undefined") return;
  if (value === null) {
    window.localStorage.removeItem(STORAGE_KEY);
  } else {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    // Read-once hydration from localStorage. Doing this in an effect (not
    // during render) keeps SSR and CSR in agreement on the first paint,
    // which is the exact case the lint rule is ok being opted out of.
    /* eslint-disable react-hooks/set-state-in-effect */
    const persisted = readPersisted();
    if (persisted) {
      setToken(persisted.token);
      setUser(persisted.user);
    }
    setHydrated(true);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await api<LoginResponse>("/api/auth/login", {
      method: "POST",
      json: { email, password },
    });
    setToken(resp.access_token);
    setUser(resp.user);
    writePersisted({ token: resp.access_token, user: resp.user });
    return resp.user;
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    writePersisted(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, token, hydrated, login, logout }),
    [user, token, hydrated, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/**
 * Client-side redirect guard. If hydrated and the current user isn't in
 * `allowedRoles`, we push them to `fallback` (the portal selector by default).
 * Returns `ready=true` only when the user is present and allowed, so callers
 * can conditionally render the real page body vs. a brief placeholder.
 */
export function useRequireRole(
  allowedRoles: Role[],
  fallback = "/",
): { ready: boolean; user: User | null } {
  const { user, hydrated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!hydrated) return;
    if (!user || !allowedRoles.includes(user.role)) {
      router.replace(fallback);
    }
  }, [hydrated, user, allowedRoles, router, fallback]);

  const ready = hydrated && user !== null && allowedRoles.includes(user.role);
  return { ready, user: ready ? user : null };
}

export { ApiError };
