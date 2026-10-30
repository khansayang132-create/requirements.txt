import { Link } from "react-router-dom";
import { Layout } from "@/components/shell/Layout";
import { Card, Empty, Metric } from "@/components/ui/Card";
import { Key } from "@/components/ui/Key";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Sig } from "@/components/ui/TxTimeline";
import { cn } from "@/lib/cn";
import { locked, released } from "@/lib/protocol";
import { useStore } from "@/lib/store";
import { formatUsdc } from "@/lib/usdc";
import { focusRing } from "@/components/ui/styles";

const btn = "inline-flex min-h-11 items-center justify-center rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors";

export default function Overview() {
  const agreements = useStore((s) => s.agreements);
  const escrowed = agreements.reduce((s, a) => s + locked(a), 0n);
  const settled = agreements.reduce((s, a) => s + released(a), 0n);
  const active = agreements.filter((a) => a.funded).flatMap((a) => a.milestones).filter((m) => m.status !== "RELEASED").length;
  const activity = agreements
    .flatMap((a) => a.milestones.map((m, i) => ({ a, m, i })))
    .filter(({ m }) => m.status === "RELEASED" || m.status === "VERIFIED")
    .sort((x, y) => (y.m.releasedAt ?? y.m.evidence?.at ?? 0) - (x.m.releasedAt ?? x.m.evidence?.at ?? 0))
    .slice(0, 8);

  return (
    <Layout>
      <section className="mb-8 rounded-3xl border border-line bg-surface p-6 md:p-10">
        <h1 className="max-w-2xl text-3xl font-bold tracking-tight text-neutral-100 md:text-5xl">
          Programmable settlement for <span className="text-violet-400">verifiable work.</span>
        </h1>
        <p className="mt-3 text-sm text-neutral-400 md:text-base">USDC held in escrow, released per verified milestone.</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/agreements/new" className={cn(btn, "bg-violet-600 text-white hover:bg-violet-700", focusRing)}>Create Agreement</Link>
          <Link to="/agreements" className={cn(btn, "border border-line text-neutral-200 hover:bg-surface-2", focusRing)}>Explore Protocol State</Link>
        </div>
      </section>

      <div className="mb-8 grid gap-4 sm:grid-cols-3">
        <Metric label="Total escrowed" value={`${formatUsdc(escrowed)}`} hint="USDC" />
        <Metric label="Total settled" value={`${formatUsdc(settled)}`} hint="USDC" />
        <Metric label="Active milestones" value={String(active)} />
      </div>

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-400">Recent settlements</h2>
      {activity.length === 0 ? <Empty text="No settlements yet." /> : (
        <Card className="p-0">
          <ul className="divide-y divide-line">
            {activity.map(({ a, m, i }) => (
              <li key={`${a.id}-${i}`}>
                <Link to={`/agreements/${a.id}?inspect=${i}`}
                  className={cn("grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 rounded-2xl px-5 py-4 hover:bg-surface-2 md:grid-cols-[2fr_1fr_1fr_auto_auto]", focusRing)}>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-neutral-100">{a.title}</span>
                    <span className="block truncate text-xs text-neutral-400">{m.title}</span>
                  </span>
                  <span className="hidden md:block"><Key value={a.worker} /></span>
                  <span className="font-mono text-sm tabular-nums text-neutral-200 md:text-right">{formatUsdc(m.amount)}</span>
                  <StatusBadge status={m.status} className="justify-self-end md:justify-self-auto" />
                  <span className="hidden md:block">{(m.releaseSig ?? m.verifySig) && <Sig sig={(m.releaseSig ?? m.verifySig)!} />}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Layout>
  );
}
