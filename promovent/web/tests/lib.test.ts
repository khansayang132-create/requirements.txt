import { describe as d, expect, it } from "vitest";
import { ApiError, api, describe } from "@/lib/api";
import { ago, pct, price, usd, utc } from "@/lib/format";

d("format", () => {
  it("formats numbers and missing values", () => {
    expect(price(0.123456)).toBe("0.123456");
    expect(price(65432.1)).toBe("65,432.10");
    expect(price(null)).toBe("–");
    expect(pct(0.0123)).toBe("1.23%");
    expect(usd(-12_500_000)).toBe("-$12.50M");
    expect(utc(Date.UTC(2026, 10, 7, 6, 5))).toBe("2026-11-07 06:05Z");
    expect(ago(1000, 61_000)).toBe("1m ago");
  });
});

d("api client", () => {
  const res = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  it("maps network failure to offline", async () => {
    const e = await api("/x", {}, () => Promise.reject(new TypeError("fetch failed"))).catch((x: ApiError) => x) as ApiError;
    expect(e).toBeInstanceOf(ApiError);
    expect(e.kind).toBe("offline");
  });
  it("maps 401 to auth with guidance and 503 to unavailable", async () => {
    expect((await api("/x", {}, () => res(401, {})).catch((x: ApiError) => x) as ApiError).message).toMatch(/Settings/);
    const u = await api("/x", {}, () => res(503, { error: "market data unavailable", detail: "binance: 403" })).catch((x: ApiError) => x) as ApiError;
    expect(u.kind).toBe("unavailable");
    expect(u.message).toBe("market data unavailable: binance: 403");
  });
  it("describes FastAPI validation errors and live rejections", () => {
    expect(describe({ detail: [{ loc: ["body", "bars"], msg: "too small" }] })).toBe("bars: too small");
    expect(describe({ detail: { rejected: "balance: free USDT 3.00 < required 50.10" } })).toMatch(/^balance/);
  });
  it("sends the API key header when set", async () => {
    sessionStorage.setItem("pv-api-key", "k".repeat(24));
    let seen = "";
    await api("/x", {}, (_u, init) => { seen = new Headers(init?.headers).get("X-API-Key") || ""; return res(200, {}); });
    expect(seen).toBe("k".repeat(24));
    sessionStorage.clear();
  });
});
