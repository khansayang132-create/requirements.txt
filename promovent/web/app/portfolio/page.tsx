"use client";
import { useApi } from "@/lib/api";
import { num, price } from "@/lib/format";
import type { Portfolio } from "@/lib/types";
import { Kpi, Panel, StateView, Table } from "@/components/ui";

type Order = { client_order_id: string; ts: string; venue: string; testnet: boolean; role: string; symbol: string; side: number; qty: number; status: string; filled_qty: number; avg_price: number | null; error: string | null };

export default function PortfolioPage() {
  const p = useApi<Portfolio>("/api/portfolio", 15000);
  const o = useApi<Order[]>("/api/live/orders", 30000);
  return (
    <>
      <h1 className="text-lg font-semibold">Portfolio</h1>
      <Panel title="Paper account">
        <StateView load={p}>{(d) => <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Equity" value={num(d.equity)} /><Kpi label="Cash" value={num(d.cash)} />
            <Kpi label="Realized P&L" value={num(d.realized_pnl)} tone={d.realized_pnl >= 0 ? "up" : "down"} /><Kpi label="Open" value={d.positions.length} />
          </div>
          <h3 className="mb-2 text-sm font-semibold">Open positions</h3>
          <Table head={["Symbol", "Side", "Qty", "Entry", "Stop", "Target", "Unrealized", "Strategy"]} empty="No open paper positions."
            rows={d.positions.map((x) => [x.symbol, x.side > 0 ? "long" : "short", num(x.qty, 5), price(x.entry), price(x.stop), price(x.target), num(x.unrealized), x.strategy])} />
          <h3 className="my-2 text-sm font-semibold">Closed trades</h3>
          <Table head={["Closed", "Symbol", "Qty", "Entry", "Exit", "Reason", "P&L"]} empty="No closed paper trades."
            rows={d.trades.map((t) => [t.closed_at?.slice(0, 16).replace("T", " "), t.symbol, num(t.qty, 5), price(t.entry), price(t.exit), t.exit_reason,
              <span key="p" className={t.pnl >= 0 ? "text-up" : "text-down"}>{num(t.pnl)}</span>])} />
        </>}</StateView>
      </Panel>
      <Panel title="Live orders (exchange)">
        <StateView load={o} isEmpty={(d) => d.length === 0} empty="No live orders have been sent.">
          {(d) => <Table head={["Time", "Venue", "Role", "Symbol", "Qty", "Filled", "Avg", "Status", "Error"]} rows={d.map((x) => [x.ts.slice(0, 19).replace("T", " "),
            `${x.venue}${x.testnet ? " (test)" : ""}`, x.role, x.symbol, num(x.qty, 6), num(x.filled_qty, 6), price(x.avg_price), x.status, x.error || "–"])} />}
        </StateView>
      </Panel>
    </>
  );
}
