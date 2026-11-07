export function num(x: number | null | undefined, d = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  return Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
}
export function price(x: number | null | undefined): string {
  if (x === null || x === undefined) return "–";
  return num(x, Math.abs(x) < 1 ? 6 : Math.abs(x) < 10 ? 4 : 2);
}
export function pct(x: number | null | undefined, d = 2): string {
  return x === null || x === undefined || Number.isNaN(x) ? "–" : `${(x * 100).toFixed(d)}%`;
}
export function usd(x: number | null | undefined): string {
  if (x === null || x === undefined) return "–";
  const a = Math.abs(x);
  return (x < 0 ? "-$" : "$") + (a >= 1e9 ? `${(a / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(1)}K` : a.toFixed(0));
}
export function ago(ms: number | null | undefined, now = Date.now()): string {
  if (!ms) return "–";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
}
export function utc(ms: number | string | null | undefined): string {
  if (!ms) return "–";
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? String(ms) : d.toISOString().slice(0, 16).replace("T", " ") + "Z";
}
export const label = (s: string) => s.replaceAll("_", " ");
