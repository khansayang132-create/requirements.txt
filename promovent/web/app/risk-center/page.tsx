"use client";
import { useState } from "react";
import { ApiError, post, useApi } from "@/lib/api";
import { label, pct } from "@/lib/format";
import type { Portfolio, Status } from "@/lib/types";
import { Dl, ErrorBox, Meter, Panel, StateView, Table } from "@/components/ui";

type Ev = { id: number; ts: string; kind: string; severity: string; detail: Record<string, unknown> };

export default function RiskCenter() {
  const st = useApi<Status>("/api/status", 30000);
  const p = useApi<Portfolio>("/api/portfolio", 15000);
  const ev = useApi<Ev[]>("/api/risk/events", 30000);
  const [err, setErr] = useState<ApiError | null>(null);
  const act = async (path: string, body?: unknown) => { setErr(null); try { await post(path, body ?? {}); p.reload(); } catch (e) { setErr(e as ApiError); } };
  return (
    <>
      <h1 className="text-lg font-semibold">Risk center</h1>
      <div className="grid-cards">
        <Panel title="Limits in use" className="lg:col-span-6">
          <StateView load={p}>{(d) => st.data ? <>
            <Meter label="Daily loss" used={d.limits.daily_loss} limit={st.data.risk.daily_loss_limit} />
            <Meter label="Weekly loss" used={d.limits.weekly_loss} limit={st.data.risk.weekly_loss_limit} />
            <Meter label="Drawdown" used={d.drawdown} limit={st.data.risk.max_drawdown} />
            <Meter label="Portfolio heat" used={d.heat} limit={st.data.risk.max_portfolio_heat} />
            {d.limits.lockouts.length ? <p className="text-sm text-down">{d.limits.lockouts.join("; ")}</p> : <p className="text-sm text-up">No lockouts.</p>}
          </> : null}</StateView>
        </Panel>
        <Panel title="Emergency stop" className="lg:col-span-6">
          <StateView load={p}>{(d) => <>
            <p className={`mb-3 font-semibold ${d.kill_switch ? "text-down" : "text-up"}`}>{d.kill_switch ? "ENGAGED: all new orders blocked" : "Ready"}</p>
            <div className="flex flex-wrap gap-2">
              <button className="btn !border-down !text-down" type="button" onClick={() => confirm("Engage emergency stop?") && act("/api/kill", { reason: "risk center" })}>Engage</button>
              <button className="btn" type="button" onClick={() => act("/api/kill/release")}>Release (admin)</button>
            </div>
          </>}</StateView>
          {err ? <div className="mt-3"><ErrorBox error={err} /></div> : null}
          {st.data ? <div className="mt-4"><Dl items={[["Risk per trade", pct(st.data.risk.risk_per_trade)], ["Max positions", st.data.risk.max_concurrent_positions],
            ["Min reward/risk", st.data.risk.min_reward_risk], ["Leverage", st.data.risk.allow_leverage ? `${st.data.risk.leverage}x` : "off"], ["Martingale", "prohibited"]]} /></div> : null}
        </Panel>
      </div>
      <Panel title="Risk events">
        <StateView load={ev} isEmpty={(e) => e.length === 0} empty="No risk events recorded.">
          {(e) => <Table head={["Time", "Severity", "Kind", "Detail"]} rows={e.map((x) => [x.ts.slice(0, 19).replace("T", " "),
            <span key="s" className={x.severity === "critical" ? "text-down" : x.severity === "warn" ? "text-accent" : ""}>{x.severity}</span>, label(x.kind),
            <code key="d" className="whitespace-normal text-xs">{JSON.stringify(x.detail)}</code>])} />}
        </StateView>
      </Panel>
    </>
  );
}
