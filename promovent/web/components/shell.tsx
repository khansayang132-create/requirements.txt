"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { post, useApi } from "@/lib/api";

const NAV: [string, string][] = [
  ["/dashboard", "Dashboard"], ["/markets", "Markets"], ["/scanner", "Scanner"], ["/trading", "Trading"], ["/portfolio", "Portfolio"],
  ["/strategies", "Strategies"], ["/backtesting", "Backtesting"], ["/whale-intelligence", "Whale intel"], ["/news", "News"],
  ["/analytics", "Analytics"], ["/risk-center", "Risk center"], ["/settings", "Settings"],
];

type Status = { mode: string; source: string; auth: string };

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const st = useApi<Status>("/api/status", 30000);
  const kill = async () => {
    if (!confirm("Engage the emergency stop? New orders are blocked until an admin releases it.")) return;
    try { await post("/api/kill", { reason: "web emergency stop" }); alert("Emergency stop engaged."); }
    catch (e) { alert(`Emergency stop failed: ${(e as Error).message}`); }
  };
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b border-line bg-surface px-4 py-3">
        <button className="btn lg:hidden" type="button" aria-expanded={open} aria-controls="nav" onClick={() => setOpen(!open)}>Menu</button>
        <Link href="/dashboard" className="text-base font-semibold text-ink no-underline">Promovent</Link>
        {st.data ? <>
          <span className="tag">mode {st.data.mode}</span>
          <span className={`tag ${st.data.source === "live" ? "" : "!border-accent !text-accent"}`}>data {st.data.source}</span>
        </> : st.error ? <span className="tag !border-down !text-down">{st.error.kind === "auth" ? "no API key" : "backend " + st.error.kind}</span> : null}
        <span className="flex-1" />
        <button className="btn !border-down !text-down" type="button" onClick={kill}>Emergency stop</button>
      </header>
      {st.data && st.data.source !== "live" ? (
        <div className="border-b border-[#5a4416] bg-[#3a2c10] px-4 py-2 text-sm font-semibold text-[#f6d48f]">
          SIMULATED DATA: this backend runs on generated prices. Nothing on these pages is market data.
        </div>
      ) : null}
      <div className="flex-1 lg:grid lg:grid-cols-[210px_1fr]">
      <nav id="nav" aria-label="Main" className={`${open ? "block" : "hidden"} border-b border-line bg-surface p-2 lg:block lg:border-b-0 lg:border-r`}>
        <ul className="grid gap-1">
          {NAV.map(([href, name]) => (
            <li key={href}>
              <Link href={href} onClick={() => setOpen(false)} aria-current={path === href ? "page" : undefined}
                className={`flex min-h-[44px] items-center rounded px-3 text-sm no-underline ${path === href ? "bg-bg font-semibold text-accent" : "text-ink hover:bg-bg"}`}>{name}</Link>
            </li>
          ))}
        </ul>
      </nav>
      <main className="mx-auto grid w-full max-w-[1500px] min-w-0 content-start gap-4 p-4">{children}</main>
      </div>
    </div>
  );
}
