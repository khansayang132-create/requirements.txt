"use client";
import { useApi } from "@/lib/api";
import { ago, label, num, pct, price } from "@/lib/format";
import type { Analysis, Portfolio, Status } from "@/lib/types";
import { DataBadge, Dl, Kpi, Meter, Panel, StateView, Table, kindOf } from "@/components/ui";

type Health = { ok: boolean; database: { ok: boolean; dialect: string }; redis: { ok: boolean; mode: string; error?: string };
  workers: Record<string, { ts: number; jobs: Record<string, { ok: boolean; detail: string }>; stream: string }>; notifications: Record<string, string> };
type Stream = { available: boolean; reason?: string; symbols?: Record<string, { price: number | null; timestamp_ms: number | null; connection: string; exchange: string; source: string }> };

export default function Dashboard() {
  const status = useApi<Status>("/api/status", 30000);
  const port = useApi<Portfolio>("/api/portfolio", 15000);
  const btc = useApi<Analysis>("/api/analysis?symbol=BTC/USDT&timeframe=1h", 60000);
  const health = useApi<Health>("/api/health", 20000);
  const stream = useApi<Stream>("/api/stream", 5000);
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
