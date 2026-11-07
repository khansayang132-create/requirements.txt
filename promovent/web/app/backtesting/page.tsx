"use client";
import { useState } from "react";
import { ApiError, post, useApi } from "@/lib/api";
import { label, num, pct } from "@/lib/format";
import { SYMBOLS } from "@/components/pickers";
import { LineChart } from "@/components/charts";
import { DataBadge, Dl, ErrorBox, Field, Panel, Table, kindOf } from "@/components/ui";
import type { Meta } from "@/lib/api";

type BT = { meta: Meta; metrics: Record<string, number>; monte_carlo: Record<string, number>; equity: { time: number; value: number }[];
  trades: { entry_time: string; side: number; entry: number; exit: number; exit_reason: string; pnl: number; r_multiple: number }[] };

export default function Backtesting() {
  const strategies = useApi<{ name: string }[]>("/api/strategies");
  const [f, setF] = useState({ strategy: "market_structure", symbol: "BTC/USDT", timeframe: "1h", bars: 1500, fee_bps: 10, slippage_bps: 3 });
  const [bt, setBt] = useState<BT | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => { setBusy(true); setErr(null); try { setBt(await post<BT>("/api/backtest", f)); } catch (e) { setErr(e as ApiError); } finally { setBusy(false); } };
  const m = bt?.metrics, mc = bt?.monte_carlo;
  return (
    <>
      <h1 className="text-lg font-semibold">Backtesting</h1>
      <Panel title="Run" badge={bt ? <DataBadge kind={kindOf(bt.meta)} meta={bt.meta} /> : undefined}>
        <form className="grid grid-cols-2 gap-3 sm:grid-cols-7" onSubmit={(e) => { e.preventDefault(); go(); }}>
          <Field label="Strategy"><select className="input" value={f.strategy} onChange={(e) => setF({ ...f, strategy: e.target.value })}>{(strategies.data || []).map((s) => <option key={s.name} value={s.name}>{label(s.name)}</option>)}</select></Field>
          <Field label="Symbol"><select className="input" value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value })}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Timeframe"><select className="input" value={f.timeframe} onChange={(e) => setF({ ...f, timeframe: e.target.value })}>{["15m", "1h", "4h", "1d"].map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Bars"><input className="input" type="number" min={300} max={5000} value={f.bars} onChange={(e) => setF({ ...f, bars: +e.target.value })} /></Field>
          <Field label="Fee bps/side"><input className="input" type="number" min={0} max={100} value={f.fee_bps} onChange={(e) => setF({ ...f, fee_bps: +e.target.value })} /></Field>
          <Field label="Slippage bps"><input className="input" type="number" min={0} max={200} value={f.slippage_bps} onChange={(e) => setF({ ...f, slippage_bps: +e.target.value })} /></Field>
          <div className="flex items-end"><button className="btn-primary w-full" type="submit" disabled={busy}>{busy ? "Running…" : "Run backtest"}</button></div>
        </form>
        {err ? <div className="mt-3"><ErrorBox error={err} /></div> : null}
        {!bt && !err ? <p className="mt-3 text-sm italic text-muted">Run a backtest to see the equity curve, metrics and trades.</p> : null}
      </Panel>
      {bt && m && mc ? <>
        <div className="grid-cards">
          <Panel title="Equity curve" className="lg:col-span-8"><LineChart points={bt.equity} label="Backtest equity curve" /></Panel>
          <Panel title="Metrics" className="lg:col-span-4"><Dl items={[["Trades", m.trades], ["Net return", pct(m.net_return)], ["Win rate", pct(m.win_rate)],
            ["Profit factor", num(m.profit_factor)], ["Sharpe", num(m.sharpe)], ["Sortino", num(m.sortino)], ["Max drawdown", pct(m.max_drawdown)], ["Calmar", num(m.calmar)],
            ["Expectancy (R)", num(m.expectancy_r)], ["Max losing streak", m.max_consecutive_losses], ["Fees paid", num(m.total_fees)],
            ["MC 95% drawdown", mc.runs ? pct(mc.max_drawdown_p95) : "–"], ["MC P(loss)", mc.runs ? pct(mc.prob_loss) : "–"]]} /></Panel>
        </div>
        <Panel title="Last trades"><Table head={["Entry time", "Side", "Entry", "Exit", "Reason", "P&L", "R"]} empty="No trades."
          rows={bt.trades.slice(-25).reverse().map((t) => [t.entry_time.slice(0, 16), t.side > 0 ? "long" : "short", num(t.entry), num(t.exit), t.exit_reason,
            <span key="p" className={t.pnl >= 0 ? "text-up" : "text-down"}>{num(t.pnl)}</span>, num(t.r_multiple)])} /></Panel>
      </> : null}
    </>
  );
}
