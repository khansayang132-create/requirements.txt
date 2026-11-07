"use client";
import { useApi } from "@/lib/api";
import { ago, label, num, pct, price } from "@/lib/format";
import type { Analysis, Portfolio, Status } from "@/lib/types";
import { DataBadge, Dl, Kpi, Meter, Panel, StateView, Table, kindOf } from "@/components/ui";

type Health = { ok: boolean; database: { ok: boolean; dialect: string }; redis: { ok: boolean; mode: string; error?: string };
  workers: Record<string, { ts: number; jobs: Record<string, { ok: boolean; detail: string }>; stream: string }>; notifications: Record<string, string> };
type Auto = { last_step: { ts: string; decision: string; entries_allowed: boolean; gates: { name: string; ok: boolean; detail: string }[];
  approved: { strategy: string; symbol: string; timeframe: string }[] } | null;
  guardian: { locked: boolean; lock: { reason: string } | null; equity: number; risk_budget_per_trade: number; daily_loss: number; drawdown: number } };
type Rep = { period: string; start: string; end: string; content: { paper: { label: string; realized_pnl_net: number; fees: number; unrealized_pnl: number; closed_trades: number } } };
type Stream = { available: boolean; reason?: string; symbols?: Record<string, { price: number | null; timestamp_ms: number | null; connection: string; exchange: string; source: string }> };

export default function Dashboard() {
  const status = useApi<Status>("/api/status", 30000);
  const port = useApi<Portfolio>("/api/portfolio", 15000);
  const btc = useApi<Analysis>("/api/analysis?symbol=BTC/USDT&timeframe=1h", 60000);
  const health = useApi<Health>("/api/health", 20000);
  const stream = useApi<Stream>("/api/stream", 5000);
  const auto = useApi<Auto>("/api/autopilot", 20000);
  const reps = useApi<Rep[]>("/api/reports?limit=60", 120000);
  const alerts = useApi<{ id: number; ts: string; kind: string; symbol: string; message: string }[]>("/api/alerts?limit=8", 30000);
  return (
    <>
      <h1 className="text-lg font-semibold">Dashboard</h1>
      <Panel title="Portfolio (paper)">
        <StateView load={port}>{(p) => (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Equity" value={num(p.equity)} />
            <Kpi label="Realized P&L" value={num(p.realized_pnl)} tone={p.realized_pnl >= 0 ? "up" : "down"} />
            <Kpi label="Open positions" value={p.positions.length} />
            <Kpi label="Portfolio heat" value={pct(p.heat)} />
            <Kpi label="Drawdown" value={pct(p.drawdown)} />
            <Kpi label="Kill switch" value={p.kill_switch ? "ENGAGED" : "ready"} tone={p.kill_switch ? "down" : undefined} />
          </div>)}
        </StateView>
      </Panel>
      <div className="grid-cards">
        <Panel title="Autopilot" className="lg:col-span-7" badge={<span className="tag">paper · live market data</span>}>
          <StateView load={auto}>{(a) => a.last_step ? <>
            <p className={`mb-2 font-semibold ${a.last_step.decision.startsWith("traded") ? "text-up" : "text-ink"}`}>{a.last_step.decision}</p>
            <ul className="grid gap-1 text-sm">{a.last_step.gates.map((g) => <li key={g.name}><span className={g.ok ? "text-up" : "text-down"}>{g.ok ? "PASS" : "BLOCK"}</span> {g.name.replaceAll("_", " ")}: <span className="text-muted">{g.detail}</span></li>)}</ul>
            <p className="mt-2 text-xs text-muted">Approved combos: {a.last_step.approved.map((x) => `${x.strategy} ${x.symbol} ${x.timeframe}`).join(", ") || "none (nothing has passed live-data validation)"} · step {a.last_step.ts.slice(0, 19)}</p>
          </> : <p className="text-sm italic text-muted">No autopilot step recorded yet: the worker runs one per minute.</p>}</StateView>
        </Panel>
        <Panel title="Risk guardian" className="lg:col-span-5">
          <StateView load={auto}>{(a) => <Dl items={[["State", a.guardian.locked ? `LOCKED: ${a.guardian.lock?.reason}` : "armed"],
            ["Equity (paper)", num(a.guardian.equity)], ["Risk budget / trade", num(a.guardian.risk_budget_per_trade, 3)],
            ["Daily loss", pct(a.guardian.daily_loss)], ["Total drawdown", pct(a.guardian.drawdown)]]} />}</StateView>
        </Panel>
      </div>
      <Panel title="P&L by period (paper, from recorded reports)">
        <StateView load={reps} isEmpty={(r) => r.length === 0} empty="No reports yet: the worker writes hourly, daily, weekly and monthly reports as each period closes.">
          {(r) => { const latest = (p: string) => r.find((x) => x.period === p);
            return <Table head={["Period", "Window", "Realized (net)", "Fees", "Unrealized", "Closed trades"]} rows={["daily", "weekly", "monthly"].map((p) => { const x = latest(p);
              return x ? [p, `${x.start.slice(0, 16)} → ${x.end.slice(0, 16)}`, num(x.content.paper.realized_pnl_net, 3), num(x.content.paper.fees, 3), num(x.content.paper.unrealized_pnl, 3), x.content.paper.closed_trades]
                : [p, "no report yet", "–", "–", "–", "–"]; })} />; }}
        </StateView>
      </Panel>
      <div className="grid-cards">
        <Panel title="BTC market regime" className="lg:col-span-4" badge={<DataBadge kind={kindOf(btc.data?.meta, btc.error)} meta={btc.data?.meta} note={btc.error?.message} />}>
          <StateView load={btc}>{(a) => <Dl items={[["Price", price(a.price)], ["Regime", label(a.regime)], ["Tradeable", a.tradeable ? "yes" : "no: stand aside"],
            ["Bias", a.bias], ["Score", `${a.score.score} (${a.score.grade})`], ["Action", a.suggested_action]]} />}</StateView>
        </Panel>
        <Panel title="Real-time stream" className="lg:col-span-4">
          <StateView load={stream}>{(s) => s.available && s.symbols ? (
            <Table head={["Pair", "Price", "Updated", "Connection"]} rows={Object.values(s.symbols).map((x) => [
              <span key="s">{x.exchange} {Object.keys(s.symbols!).find((k) => s.symbols![k] === x)}</span>, price(x.price), ago(x.timestamp_ms), x.connection])} />
          ) : <p className="text-sm"><DataBadge kind="unavailable" /> <span className="text-muted">{s.reason}</span></p>}</StateView>
        </Panel>
        <Panel title="System health" className="lg:col-span-4">
          <StateView load={health}>{(h) => <Dl items={[
            ["Database", h.database.ok ? `ok (${h.database.dialect})` : "DOWN"], ["Redis", h.redis.ok ? "ok" : `${h.redis.mode}${h.redis.error ? `: ${h.redis.error}` : ""}`],
            ["Workers", Object.keys(h.workers).length ? Object.entries(h.workers).map(([n, w]) => `${n.split("-").slice(0, 2).join("-")} ${ago(w.ts * 1000)}`).join(", ") : "none reporting"],
            ["Telegram", h.notifications.telegram], ["Email", h.notifications.email]]} />}</StateView>
        </Panel>
      </div>
      <div className="grid-cards">
        <Panel title="Risk limits" className="lg:col-span-5">
          <StateView load={port}>{(p) => status.data ? <>
            <Meter label="Daily loss" used={p.limits.daily_loss} limit={status.data.risk.daily_loss_limit} />
            <Meter label="Weekly loss" used={p.limits.weekly_loss} limit={status.data.risk.weekly_loss_limit} />
            <Meter label="Drawdown" used={p.drawdown} limit={status.data.risk.max_drawdown} />
            <Meter label="Portfolio heat" used={p.heat} limit={status.data.risk.max_portfolio_heat} />
          </> : <p className="text-sm text-muted">Waiting for limits…</p>}</StateView>
        </Panel>
        <Panel title="Recent alerts" className="lg:col-span-7">
          <StateView load={alerts} isEmpty={(a) => a.length === 0} empty="No alerts yet. They appear when the scanner finds setups, breakouts or data outages.">
            {(a) => <Table head={["When", "Symbol", "Kind", "Message"]} rows={a.map((x) => [x.ts.slice(0, 16).replace("T", " "), x.symbol, label(x.kind), x.message])} />}
          </StateView>
        </Panel>
      </div>
    </>
  );
}
