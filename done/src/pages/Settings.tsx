import { useState } from "react";
import { Layout, PageHeader } from "@/components/shell/Layout";
import { Button, ConfirmButton } from "@/components/ui/Button";
import { Card, Segmented } from "@/components/ui/Card";
import { Key } from "@/components/ui/Key";
import { focusRing, input } from "@/components/ui/styles";
import { notify } from "@/components/ui/TopDrawer";
import { cn } from "@/lib/cn";
import { PROGRAM_ID, resetState, setCluster, setMock, USDC_MINT_DEVNET, useStore, type Cluster } from "@/lib/store";

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line py-4 last:border-0">
    <span className="text-sm text-neutral-300">{label}</span>
    <div className="min-w-0">{children}</div>
  </div>
);

export default function Settings() {
  const mock = useStore((s) => s.mock);
  const cluster = useStore((s) => s.cluster);
  const [arming, setArming] = useState(false);
  const [typed, setTyped] = useState("");
  const pick = (c: Cluster) => {
    if (c === "devnet") { setArming(false); setCluster(c); } else setArming(true);
  };
  return (
    <Layout>
      <PageHeader title="Settings" sub="Network, program and local state." />
      <Card className="py-1">
        <Row label="Cluster">
          <Segmented<Cluster> label="Cluster" value={arming ? "mainnet-beta" : cluster} onChange={pick}
            options={[{ value: "devnet", label: "Devnet" }, { value: "mainnet-beta", label: "Mainnet" }]} />
        </Row>
        {arming && cluster !== "mainnet-beta" && (
          <div className="flex flex-wrap items-center gap-2 pb-4">
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type MAINNET" aria-label="Type MAINNET to confirm"
              className={`${input} max-w-48 font-mono`} />
            <Button disabled={typed !== "MAINNET"} onClick={() => { setCluster("mainnet-beta"); setArming(false); setTyped(""); }}>Switch</Button>
            <Button variant="ghost" onClick={() => { setArming(false); setTyped(""); }}>Cancel</Button>
          </div>
        )}
        <Row label="Program ID">
          {PROGRAM_ID ? <Key value={PROGRAM_ID} /> : <span className="font-mono text-xs text-amber-400">Not deployed</span>}
        </Row>
        <Row label="USDC mint">
          {cluster === "devnet" ? <Key value={USDC_MINT_DEVNET} /> : <span className="font-mono text-xs text-neutral-400">—</span>}
        </Row>
        <Row label="Mock mode">
          <button type="button" role="switch" aria-checked={mock} onClick={() => setMock(!mock)}
            className={cn("relative h-7 w-12 rounded-full transition-colors", focusRing, mock ? "bg-violet-600" : "bg-neutral-700")}>
            <span className={cn("absolute top-1 size-5 rounded-full bg-white transition-transform motion-reduce:transition-none", mock ? "translate-x-6" : "translate-x-1")} /> {/* ui-lint-ignore: switch knob, not a surface */}
            <span className="sr-only">Mock mode</span>
          </button>
        </Row>
        {!mock && <p className="pb-4 text-sm text-amber-400">No program deployed: actions will fail until mock mode is on.</p>}
        <Row label="Local state">
          <ConfirmButton onConfirm={() => { resetState(); notify("success", "Local state reset."); }}>Reset</ConfirmButton>
        </Row>
      </Card>
    </Layout>
  );
}
