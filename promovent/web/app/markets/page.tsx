"use client";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import { label, price } from "@/lib/format";
import type { Analysis, Ohlcv } from "@/lib/types";
import { CandleChart } from "@/components/charts";
import { DataBadge, Dl, Panel, StateView, kindOf } from "@/components/ui";
import { Pickers } from "@/components/pickers";

export default function Markets() {
  const [sym, setSym] = useState("BTC/USDT");
  const [tf, setTf] = useState("1h");
  const q = `symbol=${encodeURIComponent(sym)}&timeframe=${tf}`;
  const o = useApi<Ohlcv>(`/api/ohlcv?${q}&limit=300`, 60000);
  const a = useApi<Analysis>(`/api/analysis?${q}`, 60000);
  const levels = useMemo(() => o.data ? [
    ...(o.data.last_swing_high ? [{ price: o.data.last_swing_high, title: "swing high", up: false }] : []),
    ...(o.data.last_swing_low ? [{ price: o.data.last_swing_low, title: "swing low", up: true }] : [])] : [], [o.data]);
  return (
    <>
      <h1 className="text-lg font-semibold">Markets</h1>
      <div className="grid-cards">
        <Panel title={`${sym} ${tf}`} className="lg:col-span-8" actions={<Pickers {...{ sym, setSym, tf, setTf }} />}
          badge={<DataBadge kind={kindOf(o.data?.meta, o.error)} meta={o.data?.meta} note={o.error?.message} />}>
          <StateView load={o} isEmpty={(d) => d.candles.length === 0} empty="No closed candles returned.">
            {(d) => <CandleChart candles={d.candles} markers={d.breaks} levels={levels} label={`${sym} candlestick chart`} />}
          </StateView>
        </Panel>
        <Panel title="Copilot analysis" className="lg:col-span-4" badge={<DataBadge kind={kindOf(a.data?.meta, a.error)} meta={a.data?.meta} note={a.error?.message} />}>
          <StateView load={a}>{(x) => <>
            <Dl items={[["Bias", x.bias], ["Regime", label(x.regime)], ["Score", `${x.score.score} (${x.score.grade})`], ["Zone", x.zone],
              ["Entry", price(x.potential_entry)], ["Invalidation", price(x.invalidation)], ["Target 2R", price(x.target_2r)], ["RSI", x.rsi.toFixed(1)],
              ["Action", x.suggested_action]]} />
            <h3 className="mt-3 text-sm font-semibold text-up">Supporting</h3>
            <ul className="list-disc pl-5 text-sm">{(x.supporting.length ? x.supporting : ["none"]).map((s) => <li key={s}>{s}</li>)}</ul>
            <h3 className="mt-2 text-sm font-semibold text-down">Conflicting</h3>
            <ul className="list-disc pl-5 text-sm">{(x.conflicting.length ? x.conflicting : ["none"]).map((s) => <li key={s}>{s}</li>)}</ul>
            {x.score.unavailable.length ? <p className="mt-2 text-xs text-muted">No data for {x.score.unavailable.join(", ")} (scored 0).</p> : null}
          </>}</StateView>
        </Panel>
      </div>
    </>
  );
}
