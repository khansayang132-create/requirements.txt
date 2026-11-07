"use client";
import { useState } from "react";
import { ApiError, api, post, useApi } from "@/lib/api";
import { num, pct, utc } from "@/lib/format";
import { SYMBOLS } from "@/components/pickers";
import { DataBadge, Dl, ErrorBox, Field, Panel, StateView, Table } from "@/components/ui";

type M = { version: string; kind: string; trained_at: string; source: string; timeframe: string; rows: number; mean_auc: number | null; beats_baseline: boolean };
type P = { version: string; probability_up: number; horizon_bars: number; bar_time: string; predicted_at: string; data_source: string; warning: string | null;
  drift: { status: string; max_psi: number } };

export default function Analytics() {
  const models = useApi<M[]>("/api/ml/models");
  const [sym, setSym] = useState("BTC/USDT");
  const [pred, setPred] = useState<P | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<void>) => { setBusy(true); setErr(null); try { await fn(); } catch (e) { setErr(e as ApiError); } finally { setBusy(false); } };
  return (
    <>
      <h1 className="text-lg font-semibold">Analytics: machine learning</h1>
      <p className="text-sm text-muted">Models estimate the chance price is higher after N bars. Output is advisory: it never approves, sizes or blocks a trade. Validation is walk-forward with a purge gap.</p>
      <Panel title="Models" actions={<button className="btn" type="button" disabled={busy} onClick={() => act(async () => { await post("/api/ml/train", { kind: "lightgbm" }); models.reload(); })}>{busy ? "Working…" : "Train LightGBM (admin)"}</button>}>
        {err ? <ErrorBox error={err} /> : null}
        <StateView load={models} isEmpty={(m) => m.length === 0} empty="No trained models. Train one with an admin key.">
          {(m) => <Table head={["Version", "Model", "Trained", "Data", "Rows", "Mean AUC", "Beats baseline", ""]} rows={m.map((x) => [
            <span key="v" className="font-mono">{x.version}</span>, x.kind, utc(x.trained_at), <DataBadge key="d" kind={x.source === "live" ? "live" : "simulated"} />,
            x.rows, num(x.mean_auc, 3), x.beats_baseline ? "yes" : "no",
            <button key="p" className="btn" type="button" disabled={busy} onClick={() => act(async () => setPred(await api<P>(`/api/ml/predict?version=${x.version}&symbol=${encodeURIComponent(sym)}`)))}>Predict</button>])} />}
        </StateView>
        <div className="mt-3 max-w-xs"><Field label="Predict for"><select className="input" value={sym} onChange={(e) => setSym(e.target.value)}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select></Field></div>
      </Panel>
      {pred ? <Panel title="Prediction" badge={<DataBadge kind={pred.data_source === "live" ? "live" : "simulated"} />}>
        <Dl items={[["Model", pred.version], ["P(up) in " + pred.horizon_bars + " bars", pct(pred.probability_up, 1)], ["Bar", pred.bar_time], ["Predicted at", utc(pred.predicted_at)],
          ["Feature drift", `${pred.drift.status} (max PSI ${pred.drift.max_psi})`], ["Warning", pred.warning || "none"]]} />
      </Panel> : null}
    </>
  );
}
