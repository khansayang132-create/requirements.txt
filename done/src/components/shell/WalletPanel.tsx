import { useSyncExternalStore } from "react";
import { cn } from "@/lib/cn";
import { connect, IDENTITIES, useStore } from "@/lib/store";
import { formatUsdc } from "@/lib/usdc";
import { Button } from "../ui/Button";
import { InspectorPanel } from "../ui/InspectorPanel";
import { Key } from "../ui/Key";
import { focusRing } from "../ui/styles";

let isOpen = false;
const subs = new Set<() => void>();
const setOpen = (v: boolean) => { isOpen = v; subs.forEach((f) => f()); };
export const openWallet = () => setOpen(true);

/** Mock wallet picker. Real wallet adapters plug in here once a program exists. */
export function WalletPanel() {
  const open = useSyncExternalStore((f) => (subs.add(f), () => subs.delete(f)), () => isOpen);
  const onClose = () => setOpen(false);
  const wallet = useStore((s) => s.wallet);
  const balances = useStore((s) => s.balances);
  return (
    <InspectorPanel open={open} onClose={onClose} title="Connect wallet">
      <p className="mb-4 text-sm text-neutral-400">Mock wallets. Pick a role to act as.</p>
      <div className="space-y-2">
        {IDENTITIES.map((id) => (
          <button key={id.key} type="button" onClick={() => { connect(id.key); onClose(); }}
            className={cn("flex w-full items-center justify-between gap-3 rounded-xl border p-4 text-left transition-colors", focusRing,
              wallet === id.key ? "border-violet-500/50 bg-violet-600/10" : "border-line-soft bg-surface-2 hover:border-line")}>
            <span>
              <span className="block text-sm font-semibold text-neutral-100">{id.name}</span>
              <Key value={id.key} className="mt-1" />
            </span>
            <span className="font-mono text-sm tabular-nums text-neutral-300">{formatUsdc(balances[id.key] ?? 0n)}</span>
          </button>
        ))}
      </div>
      {wallet && <Button variant="secondary" className="mt-6 w-full" onClick={() => { connect(null); onClose(); }}>Disconnect</Button>}
    </InspectorPanel>
  );
}
