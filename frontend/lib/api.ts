/**
 * Typed fetch wrapper.
 *
 * The backend is proxied at /api/* via next.config.ts, so callers just pass
 * relative paths. On non-2xx responses we throw an `ApiError` carrying the
 * status and (when present) the FastAPI `detail` string, so callers can
 * distinguish "bad creds" (401) from other failures without re-parsing JSON.
 */

export class ApiError extends Error {
  status: number;
  detail: string | undefined;

  constructor(status: number, detail: string | undefined, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

type ApiInit = Omit<RequestInit, "body"> & {
  json?: unknown;
  token?: string | null;
};

export async function api<T = unknown>(path: string, init: ApiInit = {}): Promise<T> {
  const { json, token, headers, ...rest } = init;
  const h = new Headers(headers);
  if (json !== undefined) h.set("Content-Type", "application/json");
  if (token) h.set("Authorization", `Bearer ${token}`);

  const res = await fetch(path, {
    ...rest,
    headers: h,
    body: json === undefined ? (rest as RequestInit).body : JSON.stringify(json),
  });

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: string } | undefined;
      detail = typeof body?.detail === "string" ? body.detail : undefined;
    } catch {
      // response wasn't JSON — leave detail undefined
    }
    throw new ApiError(res.status, detail, detail ?? `request failed: ${res.status}`);
  }

  // 204 No Content — nothing to parse
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
