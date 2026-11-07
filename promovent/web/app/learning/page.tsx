"use client";
import { useState } from "react";
import { useApi } from "@/lib/api";
import { label, num, pct, utc } from "@/lib/format";
import { DataBadge, Dl, Panel, StateView, Table } from "@/components/ui";

type Finding = { id: number; ts: string; area: string; title: string; hypothesis: string; source: string; data_window: string; methodology: string;
  conclusion: string; summary: string; limitations: string; data_source: string };
type SR = { id: number; ts: string; strategy: string; symbol: string; timeframe: string; exchange: string; source: string; bars: number; passed: boolean;
  failures: string[]; oos_sharpe: number | null; metrics: { trades: number; net_return: number; win_rate: number; profit_factor: number; max_drawdown: number; total_fees: number } };
type Learn = { monitor: { status: string; resolved?: number; live_brier?: number | null; live_baseline_brier?: number | null; live_hit_rate?: number | null;
  promoted?: { version: string; kind: string; auc: number } | null }; recent_predictions: { symbol: string; bar_time: string; probability_up: number; outcome_up: boolean | null; model_version: string }[] };
type Auto = { mission: { id: string; status: string; started_at: string; ends_at: string; cycles: number; last_cycle_at: string | null } | null };
type Review = { ts: string; strategy: string; symbol: string; exit_reason: string; net_pnl: number; fees: number; r_multiple: number;
  evaluation: { hypothesis: string; lucky: boolean; regime_changed: boolean; execution_ok: boolean; notes: string[] } };

const tone = (c: string) => (c === "supported" ? "text-up" : c === "not_supported" ? "text-down" : "text-muted");

export default function Learning() {
  const f = useApi<Finding[]>("/api/research/findings?limit=300", 120000);
  const sr = useApi<SR[]>("/api/research/strategies?limit=500", 120000);
  const ml = useApi<Learn>("/api/learning", 60000);
  const ap = useApi<Auto>("/api/autopilot", 60000);
  const rv = useApi<Review[]>("/api/trade-reviews?limit=50", 60000);
  const [open, setOpen] = useState<number | null>(null);
  const [all, setAll] = useState(false);
  return (
    <>
      <h1 className="text-lg font-semibold">Learning and research</h1>
      <p className="text-sm text-muted">Everything here comes from recorded runs. Research uses live exchange history; a combination can trade only after it passes validation.</p>
      <div className="grid-cards">
        <Panel title="Research mission" className="lg:col-span-5">
          <StateView load={ap}>{(a) => a.mission ? <Dl items={[["Mission", a.mission.id], ["Status", a.mission.status], ["Started", utc(a.mission.started_at)],
            ["Ends", utc(a.mission.ends_at)], ["Cycles", a.mission.cycles], ["Last cycle", utc(a.mission.last_cycle_at)]]} />
            : <p className="text-sm italic text-muted">The worker starts the 72-hour mission on its first research run (live data only).</p>}</StateView>
        </Panel>
        <Panel title="Model health" className="lg:col-span-7">
          <StateView load={ml}>{(m) => <Dl items={[["Status", m.monitor.status], ["Promoted model", m.monitor.promoted ? `${m.monitor.promoted.kind} ${m.monitor.promoted.version}` : "none (no model beat the base rate)"],
            ["Resolved predictions", m.monitor.resolved ?? 0], ["Live hit rate", pct(m.monitor.live_hit_rate ?? null, 1)],
            ["Live Brier vs base rate", m.monitor.live_brier != null ? `${num(m.monitor.live_brier, 4)} vs ${num(m.monitor.live_baseline_brier ?? null, 4)}` : "–"],
            ["Authority", "advisory only: models cannot change risk controls or authorize trades"]]} />}</StateView>
        </Panel>
      </div>
      <Panel title="Research findings" badge={<span className="tag">source · date · method · limits recorded</span>}>
        <StateView load={f} isEmpty={(d) => d.length === 0} empty="No findings yet: research runs in the worker on live data.">
          {(d) => <div className="grid gap-2">{d.map((x) => (
            <div key={x.id} className="rounded border border-line p-3">
              <button type="button" className="flex w-full min-h-[44px] flex-wrap items-center gap-2 text-left" aria-expanded={open === x.id} onClick={() => setOpen(open === x.id ? null : x.id)}>
                <span className="tag">{x.area}</span><span className="font-semibold">{x.title}</span>
                <span className={`ml-auto font-mono text-xs ${tone(x.conclusion)}`}>{label(x.conclusion)}</span>
              </button>
              <p className="mt-1 text-sm">{x.summary}</p>
              {open === x.id ? <div className="mt-2"><Dl items={[["Hypothesis", x.hypothesis], ["Source", x.source], ["Data", `${x.data_window} (${x.data_source})`],
                ["Method", x.methodology], ["Limitations", x.limitations], ["Researched", utc(x.ts)]]} /></div> : null}
            </div>))}</div>}
        </StateView>
      </Panel>
      <Panel title="Strategy validation (latest runs)" badge={sr.data?.[0] ? <DataBadge kind={sr.data[0].source === "live" ? "live" : "simulated"} meta={{ exchange: sr.data[0].exchange }} /> : undefined}>
        <StateView load={sr} isEmpty={(d) => d.length === 0} empty="No strategy research recorded yet.">
          {(d) => { const ranked = [...d].sort((a, b) => Number(b.passed) - Number(a.passed) || (b.metrics.profit_factor ?? 0) - (a.metrics.profit_factor ?? 0));
            const shown = all ? ranked : ranked.slice(0, 25);
            return <>
            <p className="mb-2 text-sm text-muted">{d.filter((r) => r.passed).length} of {d.length} combinations passed. Sorted: passed first, then profit factor.</p>
            <Table head={["When", "Strategy", "Pair", "TF", "Trades", "Net", "PF", "Max DD", "OOS Sharpe", "Fees", "Gate"]} rows={shown.map((r) => [
            utc(r.ts), label(r.strategy), r.symbol, r.timeframe, r.metrics.trades, pct(r.metrics.net_return), num(r.metrics.profit_factor), pct(r.metrics.max_drawdown),
            num(r.oos_sharpe), num(r.metrics.total_fees), <span key="g" className={r.passed ? "text-up" : "text-down"} title={r.failures.join("; ")}>{r.passed ? "PASS" : "FAIL"}</span>])} />
            {d.length > 25 ? <button type="button" className="btn mt-2" onClick={() => setAll(!all)}>{all ? "Show top 25" : `Show all ${d.length}`}</button> : null}
          </>; }}
        </StateView>
      </Panel>
      <div className="grid-cards">
        <Panel title="Prediction tracking" className="lg:col-span-6">
          <StateView load={ml} isEmpty={(m) => m.recent_predictions.length === 0} empty="No predictions: nothing is logged until a model is promoted.">
            {(m) => <Table head={["Bar", "Pair", "P(up)", "Outcome"]} rows={m.recent_predictions.slice(0, 20).map((p) => [utc(p.bar_time), p.symbol, pct(p.probability_up, 1),
              p.outcome_up == null ? "pending" : p.outcome_up ? "up" : "down"])} />}
          </StateView>
        </Panel>
        <Panel title="Trade reviews" className="lg:col-span-6">
          <StateView load={rv} isEmpty={(d) => d.length === 0} empty="No closed trades yet.">
            {(d) => <Table head={["Closed", "Pair", "Exit", "Net", "R", "Prediction", "Notes"]} rows={d.map((r) => [utc(r.ts), r.symbol, r.exit_reason,
              <span key="n" className={r.net_pnl >= 0 ? "text-up" : "text-down"}>{num(r.net_pnl, 3)}</span>, num(r.r_multiple),
              r.evaluation.lucky ? "profit, not as predicted" : r.evaluation.hypothesis, r.evaluation.notes.join("; ") || "–"])} />}
          </StateView>
        </Panel>
      </div>
    </>
  );
}
