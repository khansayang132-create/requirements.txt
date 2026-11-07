"use client";
import { useState } from "react";
import { ApiError, post, useApi } from "@/lib/api";
import { label } from "@/lib/format";
import { ErrorBox, Panel, StateView } from "@/components/ui";

type S = { name: string; validated: boolean; entry_rules: string; exit_rules: string; stop_method: string; failure_conditions: string; suited_regimes: string[]; timeframes: string[] };
type Gate = { gate: { passed: boolean; failures: string[] }; meta: { source: string } };

export default function Strategies() {
  const s = useApi<S[]>("/api/strategies");
  const [res, setRes] = useState<Record<string, Gate | ApiError>>({});
  const [busy, setBusy] = useState("");
  const validate = async (name: string) => {
    setBusy(name);
    try { const r = await post<Gate>("/api/validate", { strategy: name, bars: 3000 }); setRes((x) => ({ ...x, [name]: r })); s.reload(); }
    catch (e) { setRes((x) => ({ ...x, [name]: e as ApiError })); } finally { setBusy(""); }
  };
  return (
    <>
      <h1 className="text-lg font-semibold">Strategies</h1>
      <p className="text-sm text-muted">A strategy must pass walk-forward, Monte Carlo and minimum-trade checks before it can paper or live trade. Validating needs an admin key.</p>
      <StateView load={s}>{(list) => <div className="grid-cards">{list.map((x) => {
        const r = res[x.name];
        return (
          <Panel key={x.name} title={label(x.name)} className="lg:col-span-6"
            badge={<span className={`tag ${x.validated ? "!border-up !text-up" : ""}`}>{x.validated ? "validated" : "not validated"}</span>}
            actions={<button className="btn" type="button" disabled={!!busy} onClick={() => validate(x.name)}>{busy === x.name ? "Validating…" : "Validate"}</button>}>
            <dl className="grid gap-2 text-sm">
              <div><dt className="text-muted">Entry</dt><dd>{x.entry_rules}</dd></div>
              <div><dt className="text-muted">Exit</dt><dd>{x.exit_rules}</dd></div>
              <div><dt className="text-muted">Stop</dt><dd>{x.stop_method}</dd></div>
              <div><dt className="text-muted">Fails when</dt><dd>{x.failure_conditions}</dd></div>
              <div><dt className="text-muted">Regimes · timeframes</dt><dd>{x.suited_regimes.map(label).join(", ")} · {x.timeframes.join(", ")}</dd></div>
            </dl>
            {r instanceof ApiError ? <div className="mt-2"><ErrorBox error={r} /></div> : r ? (
              <div className="mt-2 text-sm"><p className={r.gate.passed ? "text-up" : "text-down"}>{r.gate.passed ? "Passed" : "Failed"} on {r.meta.source} data</p>
                <ul className="list-disc pl-5">{r.gate.failures.map((f) => <li key={f}>{f}</li>)}</ul></div>) : null}
          </Panel>);
      })}</div>}</StateView>
    </>
  );
}
