"use client";
import { useState } from "react";
import { ApiError, post, useApi } from "@/lib/api";
import { label, num, price } from "@/lib/format";
import { SYMBOLS } from "@/components/pickers";
import { Dl, ErrorBox, Field, Panel, StateView } from "@/components/ui";

type LiveStatus = { mode: string; live_enabled: boolean; exchange: string; ready: boolean; problem?: string; testnet?: boolean;
  can_trade?: boolean; withdrawals_enabled?: boolean | null; autonomy: { active: boolean } };
type Check = { name: string; ok: boolean; detail: string };
type Pre = { ok: boolean; qty?: number; price?: number; risk_amount?: number; checks?: Check[]; failed: string[] };
type Proposal = { token: string; expires_in_s: number; symbol: string; qty: number; price: number; stop: number; target: number; preflight: Pre };
type Strategy = { name: string; validated: boolean };

function Checks({ pre }: { pre: Pre }) {
  return (
    <ul className="mt-2 grid gap-1 text-sm">
      {(pre.checks || []).map((c) => <li key={c.name + c.detail}><span className={c.ok ? "text-up" : "text-down"}>{c.ok ? "PASS" : "FAIL"}</span> {label(c.name)}{c.detail ? `: ${c.detail}` : ""}</li>)}
      {!pre.checks?.length && pre.failed.map((f) => <li key={f} className="text-down">FAIL {f}</li>)}
    </ul>
  );
}

export default function Trading() {
  const live = useApi<LiveStatus>("/api/live/status", 30000);
  const strategies = useApi<Strategy[]>("/api/strategies");
  const [form, setForm] = useState({ strategy: "market_structure", symbol: "BTC/USDT", timeframe: "1h" });
  const [pre, setPre] = useState<Pre | null>(null);
  const [prop, setProp] = useState<Proposal | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => { setBusy(true); setErr(null); try { await fn(); } catch (e) { setErr(e as ApiError); } finally { setBusy(false); } };
  const isLive = live.data?.mode === "assisted_live" || live.data?.mode === "autonomous_live";
  return (
    <>
      <h1 className="text-lg font-semibold">Trading</h1>
      <Panel title="Live execution status">
        <StateView load={live}>{(l) => <>
          <Dl items={[["Mode", l.mode], ["Live switch", l.live_enabled ? "on (PROMOVENT_ENABLE_LIVE=yes)" : "off"], ["Exchange", `${l.exchange}${l.testnet === undefined ? "" : l.testnet ? " (testnet)" : " (MAINNET)"}`],
            ["Ready", l.ready ? "yes" : "no"], ["Problem", l.problem || "none"], ["Withdrawals", l.withdrawals_enabled === undefined ? "–" : l.withdrawals_enabled ? "ENABLED on key: refused" : l.withdrawals_enabled === false ? "disabled on key" : "not reported (testnet)"],
            ["Autonomous", l.autonomy.active ? "ACTIVE" : "off"]]} />
          {!isLive ? <p className="mt-2 text-sm text-muted">Live orders need mode assisted_live or autonomous_live and PROMOVENT_ENABLE_LIVE=yes on the backend. Paper orders work in paper mode.</p> : null}
        </>}</StateView>
      </Panel>
      <Panel title="Order ticket">
        <form className="grid grid-cols-1 gap-3 sm:grid-cols-4" onSubmit={(e) => e.preventDefault()}>
          <Field label="Strategy">
            <select className="input" value={form.strategy} onChange={(e) => setForm({ ...form, strategy: e.target.value })}>
              {(strategies.data || []).map((s) => <option key={s.name} value={s.name}>{label(s.name)}{s.validated ? "" : " (not validated)"}</option>)}
            </select>
          </Field>
          <Field label="Symbol"><select className="input" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Signal timeframe"><select className="input" value={form.timeframe} onChange={(e) => setForm({ ...form, timeframe: e.target.value })}>{["15m", "1h", "4h"].map((s) => <option key={s}>{s}</option>)}</select></Field>
          <div className="flex flex-wrap items-end gap-2">
            <button className="btn" type="button" disabled={busy} onClick={() => run(async () => { setResult(await post("/api/paper/order", form)); })}>Paper order</button>
            <button className="btn" type="button" disabled={busy} onClick={() => run(async () => { setPre(await post<Pre>("/api/live/preflight", form)); setProp(null); })}>Live preflight</button>
            {live.data?.mode === "assisted_live" ? <button className="btn-primary" type="button" disabled={busy} onClick={() => run(async () => { setProp(await post<Proposal>("/api/live/propose", form)); })}>Propose live order</button> : null}
          </div>
        </form>
        {err ? <div className="mt-3"><ErrorBox error={err} /></div> : null}
        {pre ? <div className="mt-3"><p className={`font-semibold ${pre.ok ? "text-up" : "text-down"}`}>{pre.ok ? `Preflight passed: qty ${pre.qty} at ${price(pre.price)}` : "Preflight failed"}</p><Checks pre={pre} /></div> : null}
        {prop ? (
          <div className="mt-3 rounded border border-accent p-3" role="dialog" aria-label="Confirm live order">
            <p className="font-semibold text-accent">Confirm LIVE order on {live.data?.exchange}{live.data?.testnet ? " testnet" : " MAINNET"}</p>
            <Dl items={[["Buy", `${prop.qty} ${prop.symbol}`], ["Approx. price", price(prop.price)], ["Stop", price(prop.stop)], ["Target", price(prop.target)],
              ["Notional", num(prop.qty * prop.price)], ["Expires", `${prop.expires_in_s}s`]]} />
            <div className="mt-3 flex gap-2">
              <button className="btn-primary" type="button" disabled={busy} onClick={() => run(async () => { setResult(await post("/api/live/confirm", { token: prop.token, symbol: prop.symbol })); setProp(null); })}>Confirm and send</button>
              <button className="btn" type="button" onClick={() => setProp(null)}>Cancel</button>
            </div>
          </div>) : null}
        {result ? <pre className="mt-3 overflow-x-auto rounded border border-line bg-bg p-3 text-xs">{JSON.stringify(result, null, 2)}</pre> : null}
      </Panel>
    </>
  );
}
