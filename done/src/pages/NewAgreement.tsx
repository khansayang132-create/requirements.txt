import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Layout, PageHeader } from "@/components/shell/Layout";
import { openWallet } from "@/components/shell/WalletPanel";
import { Button } from "@/components/ui/Button";
import { Card, Nested, Segmented } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { Key } from "@/components/ui/Key";
import { focusRing, input, label } from "@/components/ui/styles";
import { notify } from "@/components/ui/TopDrawer";
import { TxTimeline } from "@/components/ui/TxTimeline";
import { cn } from "@/lib/cn";
import { agreementPayload, hashOf } from "@/lib/hash";
import { VERIFICATION_MODES, type VerificationMode } from "@/lib/protocol";
import { createAgreement, useStore } from "@/lib/store";
import { formatUsdc, toInput, tryParseUsdc } from "@/lib/usdc";
import { useTx } from "@/lib/useTx";
import { parseWallet } from "@/lib/wallet";

interface Draft { title: string; amount: string; mode: VerificationMode; dod: string[]; next: string }
const blank = (): Draft => ({ title: "", amount: "", mode: "Sponsor review", dod: [], next: "" });

function AddressField({ id, value, onChange, optional, self }: { id: string; value: string; onChange: (v: string) => void; optional?: boolean; self: string | null }) {
  const key = value.trim() ? parseWallet(value) : null;
  const state = !value.trim() ? "empty" : !key ? "invalid" : key.toBase58() === self ? "self" : "ok";
  return (
    <>
      <input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder={optional ? "Optional" : "Solana address"}
        spellCheck={false} autoComplete="off"
        className={cn(input, "font-mono", state === "invalid" || state === "self" ? "border-red-500/40" : state === "ok" ? "border-emerald-500/40" : "")} />
      {state === "invalid" && <p className="mt-1 text-xs text-red-400">Not a Solana wallet address</p>}
      {state === "self" && <p className="mt-1 text-xs text-red-400">Can't be your own wallet</p>}
    </>
  );
}

function AmountField({ id, value, onChange, remaining }: { id: string; value: string; onChange: (v: string) => void; remaining?: bigint }) {
  const add = (n: bigint) => onChange(toInput((tryParseUsdc(value) ?? 0n) + n));
  const bad = value.trim() !== "" && tryParseUsdc(value) === null;
  return (
    <div>
      <input id={id} inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} placeholder="0.00"
        className={cn(input, "font-mono tabular-nums", bad && "border-red-500/40")} />
      <div className="mt-2 flex flex-wrap gap-1.5">
        {[10n, 100n, 1000n].map((n) => (
          <button key={String(n)} type="button" onClick={() => add(n * 1_000_000n)}
            className={cn("min-h-11 min-w-11 rounded-lg border border-line px-2.5 font-mono text-xs text-neutral-300 hover:bg-surface-2", focusRing)}>+{String(n)}</button>
        ))}
        {remaining !== undefined && remaining > 0n && (
          <button type="button" onClick={() => add(remaining)}
            className={cn("min-h-11 rounded-lg border border-violet-500/30 px-2.5 text-xs font-medium text-violet-300 hover:bg-violet-600/10", focusRing)}>Max remaining</button>
        )}
      </div>
    </div>
  );
}

export default function NewAgreement() {
  const nav = useNavigate();
  const wallet = useStore((s) => s.wallet);
  const balance = useStore((s) => (s.wallet ? s.balances[s.wallet] ?? 0n : 0n));
  const [title, setTitle] = useState("");
  const [worker, setWorker] = useState("");
  const [verifier, setVerifier] = useState("");
  const [budget, setBudget] = useState("");
  const [scope, setScope] = useState("");
  const [ms, setMs] = useState<Draft[]>([blank()]);
  const [hash, setHash] = useState<string | null>(null);
  const { tx, pending, run } = useTx();

  const patch = (i: number, p: Partial<Draft>) => setMs((xs) => xs.map((m, j) => (j === i ? { ...m, ...p } : m)));
  const addDod = (i: number) => {
    const t = ms[i].next.trim();
    if (t) patch(i, { dod: [...ms[i].dod, t], next: "" });
  };

  const budgetU = tryParseUsdc(budget);
  const amounts = useMemo(() => ms.map((m) => tryParseUsdc(m.amount)), [ms]);
  const allocated = amounts.reduce<bigint>((s, a) => s + (a ?? 0n), 0n);
  const remaining = (budgetU ?? 0n) - allocated;
  const workerKey = useMemo(() => parseWallet(worker), [worker]);
  const verifierKey = useMemo(() => (verifier.trim() ? parseWallet(verifier) : null), [verifier]);

  // One reason, the first that applies. The button shows it instead of a paragraph.
  const blocker = useMemo(() => {
    if (!wallet) return "Connect wallet";
    if (!title.trim()) return "Add a title";
    if (!workerKey) return "Add worker address";
    if (workerKey.toBase58() === wallet) return "Worker can't be you";
    if (verifier.trim() && !verifierKey) return "Fix verifier address";
    if (!budgetU || budgetU === 0n) return "Set a budget";
    if (budgetU > balance) return "Not enough USDC";
    if (ms.some((m) => !m.title.trim())) return "Name every milestone";
    if (amounts.some((a) => !a)) return "Set every amount";
    if (ms.some((m) => m.dod.length === 0)) return "Add DoD items";
    if (remaining !== 0n) return remaining > 0n ? `${formatUsdc(remaining)} unallocated` : `Over by ${formatUsdc(-remaining)}`;
    return null;
  }, [wallet, title, workerKey, verifier, verifierKey, budgetU, balance, ms, amounts, remaining]);

  const input_ = useMemo(() => (blocker ? null : {
    title, scope, worker: workerKey!.toBase58(), verifier: verifierKey?.toBase58(), budget: budgetU!,
    milestones: ms.map((m, i) => ({ title: m.title, amount: amounts[i]!, verificationMode: m.mode, dod: m.dod })),
  }), [blocker, title, scope, workerKey, verifierKey, budgetU, ms, amounts]);

  // Live commitment preview: same function createAgreement hashes with. Debounced; "—" while invalid.
  useEffect(() => {
    if (!input_) { setHash(null); return; }
    let live = true;
    const t = setTimeout(() => hashOf(agreementPayload(input_)).then((h) => live && setHash(h)), 150);
    return () => { live = false; clearTimeout(t); };
  }, [input_]);

  const submit = () => input_ && run(async (on) => {
    const id = await createAgreement(input_, on);
    notify("success", "Agreement funded.");
    nav(`/agreements/${id}`);
  });

  useEffect(() => { if (tx.s === "failed") notify("error", tx.reason); }, [tx]);

  return (
    <Layout>
      <PageHeader title="New agreement" sub="Escrow funds against milestones." />
      <div className="grid gap-6 pb-28 lg:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          <Card className="space-y-4">
            <div>
              <label htmlFor="t" className={label}>Title</label>
              <input id="t" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80} className={input} placeholder="Landing page rebuild" />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div><label htmlFor="w" className={label}>Worker</label><AddressField id="w" value={worker} onChange={setWorker} self={wallet} /></div>
              <div><label htmlFor="v" className={label}>Verifier</label><AddressField id="v" value={verifier} onChange={setVerifier} optional self={null} /></div>
            </div>
            <div>
              <label htmlFor="b" className={label}>Total budget (USDC)</label>
              <AmountField id="b" value={budget} onChange={setBudget} />
              {wallet && <p className="mt-1.5 text-xs text-neutral-400">Balance <span className="font-mono">{formatUsdc(balance)}</span></p>}
            </div>
            <div>
              <label htmlFor="s" className={label}>Scope <span className="normal-case text-neutral-500">{scope.length}/280</span></label>
              <textarea id="s" value={scope} onChange={(e) => setScope(e.target.value)} maxLength={280} rows={2} className={cn(input, "resize-none")} placeholder="One line on what's delivered" />
            </div>
          </Card>

          <div className="space-y-4">
            {ms.map((m, i) => (
              <Nested key={i} className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-neutral-400">Milestone {i + 1}</span>
                  {ms.length > 1 && (
                    <button type="button" aria-label={`Remove milestone ${i + 1}`} onClick={() => setMs((xs) => xs.filter((_, j) => j !== i))}
                      className={cn("rounded-lg p-1.5 text-neutral-500 hover:text-red-400", focusRing)}><Icon name="trash" className="size-4" /></button>
                  )}
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div><label htmlFor={`mt${i}`} className={label}>Title</label>
                    <input id={`mt${i}`} value={m.title} onChange={(e) => patch(i, { title: e.target.value })} className={input} maxLength={60} /></div>
                  <div><label htmlFor={`ma${i}`} className={label}>Amount</label>
                    <AmountField id={`ma${i}`} value={m.amount} onChange={(v) => patch(i, { amount: v })} remaining={remaining} /></div>
                </div>
                <div>
                  <span className={label}>Verification</span>
                  <Segmented label={`Verification for milestone ${i + 1}`} value={m.mode} onChange={(v) => patch(i, { mode: v })}
                    options={VERIFICATION_MODES.map((v) => ({ value: v, label: v }))} />
                </div>
                <div>
                  <label htmlFor={`md${i}`} className={label}>Definition of done</label>
                  {m.dod.length > 0 && (
                    <ul className="mb-2 space-y-1.5">
                      {m.dod.map((d, k) => (
                        <li key={k} className="flex items-center gap-2 rounded-lg border border-line-soft bg-black px-3 py-2 text-sm">
                          <Icon name="check" className="size-4 text-violet-400" /><span className="flex-1">{d}</span>
                          <button type="button" aria-label="Remove item" onClick={() => patch(i, { dod: m.dod.filter((_, j) => j !== k) })}
                            className={cn("rounded-lg p-1 text-neutral-500 hover:text-red-400", focusRing)}><Icon name="x" className="size-3.5" /></button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="flex gap-2">
                    <input id={`md${i}`} value={m.next} onChange={(e) => patch(i, { next: e.target.value })} maxLength={120}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addDod(i); } }} className={input} placeholder="e.g. Deployed preview URL" />
                    <Button variant="secondary" onClick={() => addDod(i)} aria-label="Add item"><Icon name="plus" className="size-4" /></Button>
                  </div>
                </div>
              </Nested>
            ))}
            <Button variant="secondary" className="w-full" onClick={() => setMs((xs) => [...xs, blank()])}>
              <Icon name="plus" className="size-4" /> Add milestone
            </Button>
          </div>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <Card>
            <p className={label}>Remaining budget</p>
            <p className={cn("font-mono text-2xl tabular-nums", remaining === 0n && budgetU ? "text-emerald-400" : remaining < 0n ? "text-red-400" : "text-neutral-100")}>
              {formatUsdc(remaining)}
            </p>
            <p className="mt-1 text-xs text-neutral-400">{formatUsdc(allocated)} of {formatUsdc(budgetU ?? 0n)} allocated</p>
          </Card>
          <Card>
            <p className={label}>Commitment hash</p>
            {hash ? <Key value={hash} full className="text-violet-300" /> : <p className="font-mono text-sm text-neutral-500">—</p>}
          </Card>
          <TxTimeline tx={tx} />
        </aside>
      </div>

      <div className="fixed inset-x-0 bottom-16 z-20 border-t border-line bg-black/90 p-4 backdrop-blur md:bottom-0 md:left-64">
        <div className="mx-auto flex max-w-6xl justify-end md:px-8">
          {blocker === "Connect wallet"
            ? <Button onClick={openWallet}>Connect wallet</Button>
            : <Button disabled={!!blocker} pending={pending} onClick={submit} className="w-full md:w-auto">{blocker ?? "Initialize & Fund Escrow"}</Button>}
        </div>
      </div>
    </Layout>
  );
}
