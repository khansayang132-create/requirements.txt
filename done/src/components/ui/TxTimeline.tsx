import { cn } from "@/lib/cn";
import { getState, isMockSig, type TxState } from "@/lib/store";
import { Icon } from "./Icon";
import { Key } from "./Key";

const STEPS = ["Sign", "Send", "Confirmed", "Finalized"] as const;
const reached = (t: TxState) => ({ idle: -1, signing: 0, sending: 1, confirming: 2, finalized: 3, failed: -1 })[t.s];

export function explorerUrl(sig: string) {
  const c = getState().cluster;
  return `https://explorer.solana.com/tx/${sig}${c === "mainnet-beta" ? "" : `?cluster=${c}`}`;
}

/** A signature: mock ones are plain text (never an explorer link), real ones link out. */
export function Sig({ sig }: { sig: string }) {
  if (isMockSig(sig)) return <Key value={sig} />;
  return (
    <a href={explorerUrl(sig)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-xs text-violet-400 hover:text-violet-300">
      {sig.slice(0, 4)}…{sig.slice(-4)} <Icon name="external" className="size-3.5" />
    </a>
  );
}

export function TxTimeline({ tx }: { tx: TxState }) {
  if (tx.s === "idle") return null;
  const at = reached(tx);
  const sig = "sig" in tx ? tx.sig : undefined;
  return (
    <div className="mt-5 rounded-xl border border-line-soft bg-surface-2 p-4" aria-live="polite">
      <ol className="space-y-3">
        {STEPS.map((label, i) => {
          const done = at >= i;
          const active = at + 1 === i && tx.s !== "failed" && tx.s !== "finalized";
          return (
            <li key={label} className="flex items-center gap-3 text-sm">
              <span className={cn("size-2.5 rounded-full", done ? "bg-violet-500" : active ? "animate-pulse bg-violet-500/50" : "bg-neutral-700")} />
              <span className={done ? "text-neutral-100" : "text-neutral-400"}>{label}</span>
            </li>
          );
        })}
      </ol>
      {tx.s === "failed" && <p className="mt-3 text-sm text-red-400">{tx.reason}</p>}
      {sig && <div className="mt-3 flex items-center gap-2 text-xs text-neutral-400">Tx <Sig sig={sig} /></div>}
    </div>
  );
}
