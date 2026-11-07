"use client";
import { useState } from "react";
import { useApi } from "@/lib/api";
import { label, num, price } from "@/lib/format";
import type { Scan } from "@/lib/types";
import { DataBadge, Panel, StateView, Table, kindOf } from "@/components/ui";

export default function Scanner() {
  const [tf, setTf] = useState("1h");
  const s = useApi<Scan>(`/api/scan?timeframe=${tf}`, 120000);
  const meta = s.data?.results[0]?.meta;
  return (
    <>
      <h1 className="text-lg font-semibold">Market scanner</h1>
      <Panel title="Ranked setups" badge={<DataBadge kind={kindOf(meta, s.error)} meta={meta} note={s.error?.message} />}
        actions={<select className="input !w-auto" aria-label="Timeframe" value={tf} onChange={(e) => setTf(e.target.value)}>{["15m", "1h", "4h"].map((t) => <option key={t}>{t}</option>)}</select>}>
        <StateView load={s} isEmpty={(d) => d.results.length === 0} empty="No symbols could be scanned.">
          {(d) => <>
            <Table head={["Symbol", "Grade", "Score", "Bias", "Regime", "Price", "Vol z", "Event", "Signals"]} rows={d.results.map((r) => [
              r.symbol, <span key="g" className={`tag ${r.grade.startsWith("A") ? "!border-up !text-up" : r.grade === "B" ? "!border-accent !text-accent" : ""}`}>{r.grade}</span>,
              num(r.score, 1), <span key="b" className={r.direction === 1 ? "text-up" : r.direction === -1 ? "text-down" : "text-muted"}>{r.direction === 1 ? "bullish" : r.direction === -1 ? "bearish" : "neutral"}</span>,
              label(r.regime), price(r.price), num(r.volume_z, 1), [r.break, r.sweep === 1 ? "swept lows" : r.sweep === -1 ? "swept highs" : null].filter(Boolean).join(", ") || "–",
              Object.keys(r.signals).map(label).join(", ") || "–"])} />
            {Object.keys(d.errors).length ? <p className="mt-2 text-sm text-down">Unavailable: {Object.entries(d.errors).map(([k, v]) => `${k} (${v})`).join("; ")}</p> : null}
            <p className="mt-2 text-xs text-muted">Scores rank setups; they are not probabilities. Order flow, liquidity, sentiment and multi-timeframe factors score 0 here unless that data is supplied.</p>
          </>}
        </StateView>
      </Panel>
    </>
  );
}
