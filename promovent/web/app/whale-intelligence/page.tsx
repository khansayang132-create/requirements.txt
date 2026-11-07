"use client";
import { useApi } from "@/lib/api";
import { label, num, usd, utc } from "@/lib/format";
import { DataBadge, Panel, StateView, Table } from "@/components/ui";

type Tx = { provider: string; chain: string; tx_hash: string; ts: number; asset: string; amount: number; amount_usd: number | null; from_owner: string;
  to_owner: string; flow: string; reference: string };
type W = { transactions: Tx[]; flows: Record<string, { exchange_inflow_usd: number; exchange_outflow_usd: number; net_exchange_flow_usd: number; count: number }>;
  clusters: { asset: string; start: number; end: number; count: number; usd: number }[]; errors: Record<string, string>; fetched_at: string };

export default function Whales() {
  const w = useApi<W>("/api/whales", 60000);
  const kind = w.data && w.data.transactions.length ? "live" : "unavailable";
  return (
    <>
      <h1 className="text-lg font-semibold">Whale intelligence</h1>
      <p className="text-sm text-muted">On-chain transfers only. A move onto an exchange is not a sale, and a move off one is not a purchase; flows are labelled as transfers.</p>
      <StateView load={w}>{(d) => <>
        {Object.keys(d.errors).length ? (
          <Panel title="Providers" badge={<DataBadge kind={kind} note="no provider returned data" />}>
            <ul className="grid gap-1 text-sm">{Object.entries(d.errors).map(([k, v]) => <li key={k}><b>{k}</b>: <span className="text-down">{v}</span></li>)}</ul>
          </Panel>) : null}
        <div className="grid-cards">
          <Panel title="Exchange flows by asset" className="lg:col-span-6">
            <Table head={["Asset", "Inflow", "Outflow", "Net to exchanges", "Transfers"]} empty="No flows: no provider data."
              rows={Object.entries(d.flows).map(([a, f]) => [a, usd(f.exchange_inflow_usd), usd(f.exchange_outflow_usd),
                <span key="n" className={f.net_exchange_flow_usd > 0 ? "text-down" : "text-up"}>{usd(f.net_exchange_flow_usd)}</span>, f.count])} />
          </Panel>
          <Panel title="Transaction clusters" className="lg:col-span-6">
            <Table head={["Asset", "Window", "Count", "Value"]} empty="No clusters of 3+ large transfers within 15 minutes."
              rows={d.clusters.map((c) => [c.asset, `${utc(c.start * 1000)} → ${utc(c.end * 1000).slice(11)}`, c.count, usd(c.usd)])} />
          </Panel>
        </div>
        <Panel title="Large transfers" badge={<DataBadge kind={kind} meta={{ exchange: "whale-alert/etherscan", timestamp_ms: Date.parse(d.fetched_at) }} note="see providers" />}>
          <Table head={["Time", "Chain", "Amount", "USD", "From", "To", "Flow", "Tx"]} empty="No transfers returned."
            rows={d.transactions.map((t) => [utc(t.ts * 1000), t.chain, `${num(t.amount, 2)} ${t.asset}`, usd(t.amount_usd), t.from_owner, t.to_owner, label(t.flow),
              t.reference ? <a key="r" href={t.reference} target="_blank" rel="noopener noreferrer">{t.tx_hash.slice(0, 10)}…</a> : t.tx_hash.slice(0, 10)])} />
        </Panel>
      </>}</StateView>
    </>
  );
}
