import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Nested, Segmented } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { Key } from "@/components/ui/Key";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { focusRing, input, label } from "@/components/ui/styles";
import { notify } from "@/components/ui/TopDrawer";
import { Sig, TxTimeline } from "@/components/ui/TxTimeline";
import { cn } from "@/lib/cn";
import { evidencePayload, hashOf } from "@/lib/hash";
import type { Agreement, Milestone } from "@/lib/protocol";
import { releaseMilestone, submitEvidence, verifyMilestone } from "@/lib/store";
import { formatUsdc } from "@/lib/usdc";
import { useTx } from "@/lib/useTx";

interface P { a: Agreement; i: number; onDone: () => void }

const Amount = ({ m }: { m: Milestone }) => (
  <Nested className="mb-5 flex items-center justify-between">
    <span className="text-sm text-neutral-400">{m.title}</span>
    <span className="font-mono text-lg tabular-nums text-neutral-100">{formatUsdc(m.amount)}</span>
  </Nested>
);

/** Shared tail: the action button until the tx starts, the timeline after, "Done" once final. */
function Act({ label: text, disabled, tx, pending, onClick, onDone }: {
  label: string; disabled?: boolean; tx: ReturnType<typeof useTx>["tx"]; pending: boolean; onClick: () => void; onDone: () => void;
}) {
  useEffect(() => {
    if (tx.s === "failed") notify("error", tx.reason);
    if (tx.s === "finalized") notify("success", `${text}: finalized.`);
  }, [tx, text]);
  return (
    <>
      {tx.s === "finalized"
        ? <Button variant="secondary" className="mt-5 w-full" onClick={onDone}>Done</Button>
        : <Button className="mt-5 w-full" disabled={disabled} pending={pending} onClick={onClick}>{tx.s === "failed" ? "Try again" : text}</Button>}
      <TxTimeline tx={tx} />
    </>
  );
}

const PROOF_TYPES = ["Link", "Commit", "Document"] as const;

export function EvidencePanel({ a, i, onDone }: P) {
  const m = a.milestones[i];
  const [type, setType] = useState<(typeof PROOF_TYPES)[number]>("Link");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [hash, setHash] = useState<string | null>(null);
  const { tx, pending, run } = useTx();
  const urlOk = useMemo(() => { try { return ["http:", "https:"].includes(new URL(url.trim()).protocol); } catch { return false; } }, [url]);
  const ev = useMemo(() => ({ type, url, notes }), [type, url, notes]);
  useEffect(() => {
    if (!urlOk) { setHash(null); return; }
    let live = true;
    const t = setTimeout(() => hashOf(evidencePayload(ev)).then((h) => live && setHash(h)), 150);
    return () => { live = false; clearTimeout(t); };
  }, [ev, urlOk]);

  return (
    <div>
      <Amount m={m} />
      <span className={label}>Proof type</span>
      <Segmented label="Proof type" value={type} onChange={setType} options={PROOF_TYPES.map((v) => ({ value: v, label: v }))} className="mb-4" />
      <label htmlFor="ev-url" className={label}>Link</label>
      <input id="ev-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" inputMode="url" spellCheck={false}
        className={cn(input, "font-mono", url && !urlOk && "border-red-500/40")} />
      <label htmlFor="ev-notes" className={cn(label, "mt-4")}>Notes</label>
      <textarea id="ev-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={280} className={cn(input, "resize-none")} />
      <p className={cn(label, "mt-4")}>Evidence hash</p>
      {hash ? <Key value={hash} full className="text-violet-300" /> : <p className="font-mono text-sm text-neutral-500">—</p>}
      <Act label="Submit Proof" disabled={!urlOk} tx={tx} pending={pending} onDone={onDone}
        onClick={() => run((on) => submitEvidence(a.id, i, ev, on))} />
    </div>
  );
}

export function VerifyPanel({ a, i, onDone }: P) {
  const m = a.milestones[i];
  const [checked, setChecked] = useState<boolean[]>(() => m.dod.map(() => false));
  const { tx, pending, run } = useTx();
  const all = checked.every(Boolean);
  return (
    <div>
      <Amount m={m} />
      {m.evidence && (
        <Nested className="mb-5 space-y-2 text-sm">
          <p className={label}>Evidence · {m.evidence.type}</p>
          <a href={m.evidence.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 break-all font-mono text-xs text-violet-400 hover:text-violet-300">
            {m.evidence.url} <Icon name="external" className="size-3.5 shrink-0" />
          </a>
          {m.evidence.notes && <p className="text-neutral-300">{m.evidence.notes}</p>}
          <Key value={m.evidence.hash} />
        </Nested>
      )}
      <p className={label}>Definition of done</p>
      <ul className="space-y-2">
        {m.dod.map((d, k) => (
          <li key={k}>
            <label className={cn("flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border px-3 py-2 text-sm transition-colors",
              checked[k] ? "border-emerald-500/30 bg-emerald-500/5 text-neutral-100" : "border-line-soft bg-surface-2 text-neutral-300")}>
              <input type="checkbox" checked={checked[k]} disabled={tx.s !== "idle" && tx.s !== "failed"}
                onChange={() => setChecked((c) => c.map((v, j) => (j === k ? !v : v)))}
                className={cn("size-4 accent-violet-600", focusRing)} />
              {d}
            </label>
          </li>
        ))}
      </ul>
      <Act label={all ? "Confirm & Verify" : `${checked.filter(Boolean).length} / ${m.dod.length} checked`} disabled={!all}
        tx={tx} pending={pending} onDone={onDone} onClick={() => run((on) => verifyMilestone(a.id, i, on))} />
    </div>
  );
}

export function SettlePanel({ a, i, onDone }: P) {
  const m = a.milestones[i];
  const { tx, pending, run } = useTx();
  return (
    <div>
      <Amount m={m} />
      <dl className="space-y-3 text-sm">
        <div className="flex justify-between gap-3"><dt className="text-neutral-400">Recipient</dt><dd><Key value={a.worker} /></dd></div>
        <div className="flex justify-between gap-3"><dt className="text-neutral-400">Status</dt><dd><StatusBadge status={m.status} /></dd></div>
        {m.verifySig && <div className="flex justify-between gap-3"><dt className="text-neutral-400">Verified in</dt><dd><Sig sig={m.verifySig} /></dd></div>}
      </dl>
      <Act label="Release USDC" tx={tx} pending={pending} onDone={onDone} onClick={() => run((on) => releaseMilestone(a.id, i, on))} />
    </div>
  );
}

export function DetailsPanel({ a, i }: { a: Agreement; i: number }) {
  const m = a.milestones[i];
  const rows: [string, React.ReactNode][] = [
    ["Status", <StatusBadge status={m.status} />],
    ["Verification", <span className="text-neutral-200">{m.verificationMode}</span>],
  ];
  if (m.evidence) rows.push(["Evidence tx", <Sig sig={m.evidence.sig} />], ["Evidence hash", <Key value={m.evidence.hash} />]);
  if (m.verifySig) rows.push(["Verify tx", <Sig sig={m.verifySig} />]);
  if (m.releaseSig) rows.push(["Release tx", <Sig sig={m.releaseSig} />]);
  return (
    <div>
      <Amount m={m} />
      <dl className="mb-5 space-y-3 text-sm">
        {rows.map(([k, v]) => <div key={k} className="flex items-center justify-between gap-3"><dt className="text-neutral-400">{k}</dt><dd>{v}</dd></div>)}
      </dl>
      <p className={label}>Definition of done</p>
      <ul className="space-y-1.5">
        {m.dod.map((d, k) => (
          <li key={k} className="flex items-center gap-2 rounded-lg border border-line-soft bg-surface-2 px-3 py-2 text-sm text-neutral-300">
            <Icon name="check" className={cn("size-4", m.status === "VERIFIED" || m.status === "RELEASED" ? "text-emerald-400" : "text-neutral-600")} />{d}
          </li>
        ))}
      </ul>
      {m.evidence?.url && (
        <a href={m.evidence.url} target="_blank" rel="noreferrer" className="mt-4 flex items-center gap-1 break-all font-mono text-xs text-violet-400 hover:text-violet-300">
          {m.evidence.url} <Icon name="external" className="size-3.5 shrink-0" />
        </a>
      )}
    </div>
  );
}
