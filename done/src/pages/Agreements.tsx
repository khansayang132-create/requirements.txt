import { Link, useSearchParams } from "react-router-dom";
import { Layout, PageHeader } from "@/components/shell/Layout";
import { Card, Empty, Segmented } from "@/components/ui/Card";
import { Key } from "@/components/ui/Key";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StepTrack } from "@/components/ui/StepTrack";
import { focusRing } from "@/components/ui/styles";
import { cn } from "@/lib/cn";
import { agreementStatus, locked, released, type Agreement } from "@/lib/protocol";
import { useStore } from "@/lib/store";
import { formatUsdc } from "@/lib/usdc";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "sponsoring", label: "Sponsoring" },
  { value: "assigned", label: "Assigned" },
  { value: "completed", label: "Completed" },
] as const;
type F = (typeof FILTERS)[number]["value"];

export const NewLink = () => (
  <Link to="/agreements/new" className={cn("inline-flex min-h-11 items-center rounded-xl bg-violet-600 px-4 text-sm font-semibold text-white hover:bg-violet-700", focusRing)}>
    New Agreement
  </Link>
);

export function AgreementCard({ a }: { a: Agreement }) {
  return (
    <Link to={`/agreements/${a.id}`} className={cn("block rounded-2xl", focusRing)}>
      <Card className="h-full transition-colors hover:border-violet-500/40">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-neutral-100">{a.title}</h2>
            <p className="mt-1 flex items-center gap-1 text-xs text-neutral-400">Worker <Key value={a.worker} /></p>
          </div>
          <StatusBadge status={agreementStatus(a)} />
        </div>
        <div className="mt-5"><StepTrack statuses={a.milestones.map((m) => m.status)} /></div>
        <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-line pt-4">
          <div><dt className="text-xs text-neutral-400">Escrowed</dt><dd className="font-mono text-sm tabular-nums">{formatUsdc(locked(a))}</dd></div>
          <div><dt className="text-xs text-neutral-400">Released</dt><dd className="font-mono text-sm tabular-nums">{formatUsdc(released(a))}</dd></div>
        </dl>
      </Card>
    </Link>
  );
}

export default function Agreements() {
  const [params, setParams] = useSearchParams();
  const f = (FILTERS.some((x) => x.value === params.get("f")) ? params.get("f") : "all") as F;
  const { agreements, wallet } = useStore((s) => s);
  const list = agreements.filter((a) =>
    f === "all" ? true
      : f === "sponsoring" ? a.sponsor === wallet
      : f === "assigned" ? a.worker === wallet
      : agreementStatus(a) === "COMPLETED");
  const needsWallet = (f === "sponsoring" || f === "assigned") && !wallet;

  return (
    <Layout>
      <PageHeader title="Agreements" sub={`${agreements.length} on record`} action={<NewLink />} />
      <Segmented label="Filter" value={f} options={FILTERS} className="mb-6"
        onChange={(v) => setParams(v === "all" ? {} : { f: v }, { replace: true })} />
      {list.length === 0
        ? <Empty text={needsWallet ? "Connect a wallet to filter by role." : "Nothing here yet."} action={!needsWallet && <NewLink />} />
        : <div className="grid gap-4 md:grid-cols-2">{list.map((a) => <AgreementCard key={a.id} a={a} />)}</div>}
    </Layout>
  );
}
