"use client";
import type { ReactNode } from "react";
import type { ApiError, Load, Meta } from "@/lib/api";
import { ago, utc } from "@/lib/format";

export function Panel({ title, children, actions, className = "", badge }: { title: string; children: ReactNode; actions?: ReactNode; className?: string; badge?: ReactNode }) {
  return (
    <section className={`min-w-0 rounded-md border border-line bg-surface p-4 ${className}`} aria-label={title}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-muted">{title}</h2>
        {badge}
        <div className="ml-auto flex flex-wrap gap-2">{actions}</div>
      </div>
      {children}
    </section>
  );
}

export type DataKind = "live" | "simulated" | "unavailable";
export function kindOf(meta?: Pick<Meta, "source"> | null, error?: ApiError): DataKind {
  if (error && !meta) return "unavailable";
  if (!meta) return "unavailable";
  return meta.source === "live" ? "live" : "simulated";
}

export function DataBadge({ kind, meta, note }: { kind: DataKind; meta?: Partial<Meta> | null; note?: string }) {
  const style = { live: "border-up text-up", simulated: "border-accent text-accent", unavailable: "border-down text-down" }[kind];
  const text = { live: "LIVE", simulated: "SIMULATED", unavailable: "UNAVAILABLE" }[kind];
  const detail = kind === "unavailable" ? note : [meta?.exchange, meta?.timestamp_ms ? `${utc(meta.timestamp_ms)} (${ago(meta.timestamp_ms)})` : null].filter(Boolean).join(" · ");
  return (
    <span className="inline-flex flex-wrap items-center gap-2 text-xs">
      <span className={`rounded border px-1.5 py-0.5 font-mono font-semibold ${style}`} data-testid="data-badge">{text}</span>
      {detail ? <span className="font-mono text-muted">{detail}</span> : null}
    </span>
  );
}

export function StateView<T>({ load, empty, isEmpty, children }: { load: Load<T>; empty?: string; isEmpty?: (d: T) => boolean; children: (d: T) => ReactNode }) {
  if (load.data === undefined) {
    if (load.error) return <ErrorBox error={load.error} retry={load.reload} />;
    return <p className="animate-pulse text-sm text-muted" role="status">Loading…</p>;
  }
  return (
    <>
      {load.error ? <ErrorBox error={load.error} retry={load.reload} stale /> : null}
      {isEmpty && isEmpty(load.data) ? <p className="text-sm italic text-muted">{empty || "Nothing to show yet."}</p> : children(load.data)}
    </>
  );
}

export function ErrorBox({ error, retry, stale }: { error: ApiError; retry?: () => void; stale?: boolean }) {
  const title = { offline: "Offline", auth: "Not authorized", unavailable: "Unavailable", error: "Error" }[error.kind];
  return (
    <div role="alert" className="mb-3 rounded border border-down/60 bg-down/10 p-3 text-sm">
      <p className="font-semibold text-down">{title}{stale ? " (showing last good data)" : ""}</p>
      <p className="mt-1 break-words text-ink">{error.message}</p>
      {retry ? <button className="btn mt-2" onClick={retry} type="button">Retry</button> : null}
    </div>
  );
}

export function Kpi({ label, value, tone }: { label: string; value: ReactNode; tone?: "up" | "down" }) {
  return (
    <div className="border-l-2 border-line pl-3">
      <span className="block text-xs text-muted">{label}</span>
      <b className={`font-mono text-lg font-semibold ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : ""}`}>{value}</b>
    </div>
  );
}

export function Meter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const r = limit ? Math.min(1, Math.max(0, used / limit)) : 0;
  const color = r > 0.85 ? "bg-down" : r > 0.5 ? "bg-accent" : "bg-up";
  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm"><span>{label}</span><span className="font-mono">{(used * 100).toFixed(2)}% / {(limit * 100).toFixed(2)}%</span></div>
      <div className="mt-1 h-2 overflow-hidden rounded border border-line bg-bg" role="meter" aria-label={label} aria-valuenow={Math.round(r * 100)} aria-valuemin={0} aria-valuemax={100}>
        <i className={`block h-full ${color}`} style={{ width: `${r * 100}%` }} />
      </div>
    </div>
  );
}

export function Table({ head, rows, empty }: { head: string[]; rows: ReactNode[][]; empty?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead><tr>{head.map((h) => <th key={h} className="whitespace-nowrap border-b border-line px-2 py-2 text-left text-xs font-semibold text-muted">{h}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 ? <tr><td colSpan={head.length} className="px-2 py-3 italic text-muted">{empty || "No rows."}</td></tr> :
            rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="whitespace-nowrap border-b border-line px-2 py-2">{c}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

export function Dl({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {items.map(([k, v]) => [<dt key={`${k}-t`} className="text-muted">{k}</dt>, <dd key={`${k}-d`} className="m-0 break-words font-mono">{v}</dd>])}
    </dl>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1 text-xs text-muted">{label}{children}</label>;
}
