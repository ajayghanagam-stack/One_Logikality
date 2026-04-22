/**
 * Per-org "last-viewed packet" persistence.
 *
 * The ECV page writes this key on each successful load so the sidebar's
 * "ECV Dashboard" link can deep-link straight back to it from anywhere.
 *
 * Why `useSyncExternalStore`: this is state that lives outside React
 * (in `localStorage`), and React's lint (`react-hooks/set-state-in-effect`)
 * correctly flags the naive "read in useEffect + setState" pattern as
 * tearing-prone. `useSyncExternalStore` is the blessed alternative and
 * also gives us a free server snapshot for SSR.
 *
 * Same-tab writes don't fire the cross-tab `storage` event, so callers
 * use `writeLastPacketId` / `clearLastPacketId` which also dispatch a
 * local `CustomEvent` that the subscriber in this module picks up.
 */

import { useSyncExternalStore } from "react";

const LOCAL_EVENT = "logikality:lastPacketChanged";

function storageKeyFor(orgSlug: string): string {
  return `logikality:lastPacketId:${orgSlug}`;
}

function subscribe(cb: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  // `storage` covers cross-tab writes; `LOCAL_EVENT` covers same-tab writes
  // performed by `writeLastPacketId` / `clearLastPacketId`.
  window.addEventListener("storage", cb);
  window.addEventListener(LOCAL_EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(LOCAL_EVENT, cb);
  };
}

export function useLastPacketId(orgSlug: string | null | undefined): string | null {
  return useSyncExternalStore(
    subscribe,
    () => {
      if (!orgSlug) return null;
      if (typeof window === "undefined") return null;
      return window.localStorage.getItem(storageKeyFor(orgSlug));
    },
    () => null,
  );
}

export function writeLastPacketId(orgSlug: string, packetId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKeyFor(orgSlug), packetId);
  window.dispatchEvent(new Event(LOCAL_EVENT));
}

export function clearLastPacketId(orgSlug: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(storageKeyFor(orgSlug));
  window.dispatchEvent(new Event(LOCAL_EVENT));
}
