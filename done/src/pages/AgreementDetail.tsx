import { useCallback, useEffect, useRef } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Layout } from "@/components/shell/Layout";
import { openWallet } from "@/components/shell/WalletPanel";
import { Button } from "@/components/ui/Button";
import { Card, Empty } from "@/components/ui/Card";
import { InspectorPanel } from "@/components/ui/InspectorPanel";
import { Key } from "@/components/ui/Key";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { focusRing } from "@/components/ui/styles";
import { cn } from "@/lib/cn";
import { agreementStatus, allowedActions, firstOpenIndex, locked, released, rolesOf, type Action } from "@/lib/protocol";
import { useStore } from "@/lib/store";
import { formatUsdc } from "@/lib/usdc";
import { DetailsPanel, EvidencePanel, SettlePanel, VerifyPanel } from "@/panels/Panels";

const PANEL: Record<Action, { key: string; label: string; title: string }> = {
  submitEvidence: { key: "evidence", label: "Submit Evidence", title: "Submit evidence" },
  verify: { key: "verify", label: "Run Verification", title: "Verify milestone" },
  release: { key: "settle", label: "Release USDC", title: "Release escrow" },
};

export default function AgreementDetail() {
  const { id } = useParams();
  const a = useStore((s) => s.agreements.find((x) => x.id === id));
  const wallet = useStore((s) => s.wallet);
  const [params, setParams] = useSearchParams();
  const raw = params.get("inspect");
  const open = raw !== null && a ? Math.min(Math.max(Number(raw) || 0, 0), a.milestones.length - 1) : null;
  const panelKey = params.get("panel");

  const inspect = useCallback((i: number | null, panel?: string) => {
    setParams(i === null ? {} : panel ? { inspect: String(i), panel } : { inspect: String(i) }, { replace: i !== null && raw !== null });
  }, [setParams, raw]);
  const close = useCallback(() => inspect(null), [inspect]);

  // [ and ] step through milestones while the inspector is open.
  useEffect(() => {
    if (open === null || !a) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input,textarea")) return;
      if (e.key === "[" && open > 0) inspect(open - 1);
      if (e.key === "]" && open < a.milestones.length - 1) inspect(open + 1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, a, inspect]);

  if (!a) return <Layout><Empty text="Agreement not found." action={<Link to="/agreements" className="text-sm text-violet-400">Back to agreements</Link>} /></Layout>;

  const roles = rolesOf(wallet, a);
  const nextOpen = firstOpenIndex(a.milestones);
  const actions = open !== null ? allowedActions(roles, a, open) : [];
  const chosen = actions.find((x) => PANEL[x].key === panelKey) ?? actions[0];
  // The panel is picked when the user navigates (milestone, panel or wallet change), not when the status
  // changes: a confirmed tx moves the status on, and the panel must stay to show its timeline to the end.
  const nav = `${open}|${panelKey}|${wallet}`;
  const sticky = useRef<{ nav: string; action?: Action }>();
  if (!sticky.current || sticky.current.nav !== nav) sticky.current = { nav, action: chosen };
  const action = sticky.current.action;
  const panelTitle = open === null ? "" : action ? PANEL[action].title : `Milestone ${open + 1}`;

  return (
    <Layout wide={open !== null}>
      <Link to="/agreements" className={cn("mb-2 inline-flex min-h-11 items-center rounded-lg text-sm text-neutral-400 hover:text-neutral-200", focusRing)}>← Agreements</Link>
      <Card className="mb-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-neutral-100">{a.title}</h1>
            {a.scope && <p className="mt-1 text-sm text-neutral-400">{a.scope}</p>}
          </div>
          <StatusBadge status={agreementStatus(a)} />
        </div>
        <dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="text-xs text-neutral-400">Locked</dt><dd className="font-mono text-xl tabular-nums">{formatUsdc(locked(a))}</dd></div>
          <div><dt className="text-xs text-neutral-400">Released</dt><dd className="font-mono text-xl tabular-nums">{formatUsdc(released(a))}</dd></div>
          <div><dt className="text-xs text-neutral-400">Sponsor</dt><dd><Key value={a.sponsor} /></dd></div>
          <div><dt className="text-xs text-neutral-400">Worker</dt><dd><Key value={a.worker} /></dd></div>
          {a.verifier && <div><dt className="text-xs text-neutral-400">Verifier</dt><dd><Key value={a.verifier} /></dd></div>}
          <div className="sm:col-span-2"><dt className="text-xs text-neutral-400">Commitment</dt><dd><Key value={a.commitment} /></dd></div>
        </dl>
        {!wallet && <Button variant="secondary" className="mt-5" onClick={openWallet}>Connect to act</Button>}
        {wallet && roles.length === 0 && <p className="mt-5 text-sm text-neutral-400">View only: this wallet has no role here.</p>}
      </Card>

      <ol className="relative space-y-3">
        {a.milestones.map((m, i) => {
          const acts = allowedActions(roles, a, i);
          return (
            <li key={i} className="flex gap-3">
              <span className={cn("mt-5 grid size-7 shrink-0 place-items-center rounded-full font-mono text-xs",
                m.status === "RELEASED" ? "bg-violet-600 text-white" : i === nextOpen ? "border border-violet-500/50 text-violet-300" : "border border-line text-neutral-500")}>{i + 1}</span>
              <div role="button" tabIndex={0} onClick={() => inspect(i)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inspect(i); } }}
                aria-label={`Inspect milestone ${i + 1}`}
                className={cn("min-w-0 flex-1 cursor-pointer rounded-2xl border bg-surface p-5 transition-colors hover:border-violet-500/40", focusRing,
                  open === i ? "border-violet-500/50" : "border-line")}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-base font-semibold text-neutral-100">{m.title}</h2>
                    <p className="mt-1 text-xs text-neutral-400">{m.verificationMode} · {m.dod.length} DoD items</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm tabular-nums">{formatUsdc(m.amount)}</span>
                    <StatusBadge status={m.status} />
                  </div>
                </div>
                {acts.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {acts.map((x) => (
                      <Button key={x} onClick={(e) => { e.stopPropagation(); inspect(i, PANEL[x].key); }}>{PANEL[x].label}</Button>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      <InspectorPanel open={open !== null} onClose={close} title={panelTitle}>
        {open !== null && (
          action === "submitEvidence" ? <EvidencePanel key={`${a.id}-${open}-e`} a={a} i={open} onDone={close} />
          : action === "verify" ? <VerifyPanel key={`${a.id}-${open}-v`} a={a} i={open} onDone={close} />
          : action === "release" ? <SettlePanel key={`${a.id}-${open}-r`} a={a} i={open} onDone={close} />
          : <DetailsPanel a={a} i={open} />
        )}
      </InspectorPanel>
    </Layout>
  );
}
