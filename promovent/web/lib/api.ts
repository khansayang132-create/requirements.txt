"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export type Meta = { exchange: string; symbol: string; timestamp_ms: number; age_seconds?: number; source: "live" | "synthetic" | "fixture" };

export class ApiError extends Error {
  constructor(public status: number, message: string, public kind: "offline" | "auth" | "unavailable" | "error") {
    super(message);
  }
}

const KEY = "pv-api-key";
export function getKey(): string {
  try { return sessionStorage.getItem(KEY) || ""; } catch { return ""; }
}
export function setKey(k: string) {
  try { k ? sessionStorage.setItem(KEY, k) : sessionStorage.removeItem(KEY); } catch { /* storage blocked */ }
}

export function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    if (typeof d.rejected === "string") return d.rejected;
    if (Array.isArray(d.detail)) return d.detail.map((x: { msg?: string; loc?: unknown[] }) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("; ");
    if (typeof d.error === "string") return d.error + (d.detail ? `: ${describe(d.detail)}` : "");
    if ("detail" in d) return describe(d.detail);
  }
  return "unexpected response";
}

export async function api<T>(path: string, init: RequestInit = {}, fetcher: typeof fetch = fetch): Promise<T> {
  let r: Response;
  try {
    r = await fetcher(path, { ...init, headers: { "Content-Type": "application/json", ...(getKey() ? { "X-API-Key": getKey() } : {}), ...(init.headers || {}) } });
  } catch {
    throw new ApiError(0, "Backend unreachable. Check your connection or that the API is running.", "offline");
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const kind = r.status === 401 || r.status === 403 ? "auth" : r.status === 503 || r.status === 502 ? "unavailable" : "error";
    const msg = r.status === 401 ? "API key missing or invalid. Set it in Settings." : describe(body);
    throw new ApiError(r.status, msg, kind);
  }
  return body as T;
}

export type Load<T> = { data?: T; error?: ApiError; loading: boolean; reload: () => void; at?: number };

export function useApi<T>(path: string | null, pollMs = 0): Load<T> {
  const [state, setState] = useState<{ data?: T; error?: ApiError; loading: boolean; at?: number }>({ loading: !!path });
  const seq = useRef(0);
  const load = useCallback(() => {
    if (!path) return;
    const n = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    api<T>(path)
      .then((data) => n === seq.current && setState({ data, loading: false, at: Date.now() }))
      .catch((error: ApiError) => n === seq.current && setState((s) => ({ data: s.data, error, loading: false, at: s.at })));
  }, [path]);
  useEffect(() => {
    load();
    if (!pollMs) return;
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, [load, pollMs]);
  return { ...state, reload: load };
}

export async function post<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  return api<T>(path, { method, body: JSON.stringify(body) });
}
