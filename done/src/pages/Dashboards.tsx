import { Link } from "react-router-dom";
import { Layout, PageHeader } from "@/components/shell/Layout";
import { openWallet } from "@/components/shell/WalletPanel";
import { Button } from "@/components/ui/Button";
import { Card, Empty, Metric } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { focusRing } from "@/components/ui/styles";
import { cn } from "@/lib/cn";
import { firstOpenIndex, locked, released, type Agreement, type Milestone } from "@/lib/protocol";
import { useStore } from "@/lib/store";
import { formatUsdc } from "@/lib/usdc";
import { AgreementCard, NewLink } from "./Agreements";

interface Item { a: Agreement; m: Milestone; i: number }
const sum = (xs: Item[]) => xs.reduce((s, x) => s + x.m.amount, 0n);
/** Milestones that are next in line (sequential) for each agreement. */
const current = (as: Agreement[]): Item[] =>
  as.filter((a) => a.funded).flatMap((a) => { const i = firstOpenIndex(a.milestones); return i < a.milestones.length ? [{ a, m: a.milestones[i], i }] : []; });

function Queue({ items, panel, cta, empty }: { items: Item[]; panel: string; cta: string; empty: string }) {
  if (items.length === 0) return <Empty text={empty} />;
  return (
    <Card className="p-0">
      <ul className="divide-y divide-line">
        {items.map(({ a, m, i }) => (
          <li key={`${a.id}-${i}`} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-neutral-100">{m.title}</p>
              <p className="truncate text-xs text-neutral-400">{a.title}</p>
            </div>
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm tabular-nums">{formatUsdc(m.amount)}</span>
              <StatusBadge status={m.status} />
              <Link to={`/agreements/${a.id}?inspect=${i}&panel=${panel}`}
                className={cn("inline-flex min-h-10 items-center rounded-xl bg-violet-600 px-3 text-sm font-semibold text-white hover:bg-violet-700", focusRing)}>{cta}</Link>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

const NeedWallet = ({ title }: { title: string }) => (
  <Layout>
    <PageHeader title={title} />
    <Empty text="Connect a wallet to see your queue." action={<Button onClick={openWallet}>Connect wallet</Button>} />
  </Layout>
);

export function Sponsor() {
  const wallet = useStore((s) => s.wallet);
  const all = useStore((s) => s.agreements);
  if (!wallet) return <NeedWallet title="Sponsor" />;
  const mine = all.filter((a) => a.sponsor === wallet);
  const verifying = all.filter((a) => a.sponsor === wallet || a.verifier === wallet);
  const now = current(verifying);
  const review = now.filter((x) => x.m.status === "EVIDENCE_SUBMITTED").sort((p, q) => (p.m.evidence?.at ?? 0) - (q.m.evidence?.at ?? 0));
  const release = now.filter((x) => x.m.status === "VERIFIED" && x.a.sponsor === wallet);
  return (
    <Layout>
      <PageHeader title="Sponsor" sub="Escrow health and review queue." action={<NewLink />} />
      <div className="mb-8 grid gap-4 sm:grid-cols-3">
        <Metric label="Locked" value={formatUsdc(mine.reduce((s, a) => s + locked(a), 0n))} hint="USDC in escrow" />
        <Metric label="Released" value={formatUsdc(mine.reduce((s, a) => s + released(a), 0n))} hint="USDC paid out" />
        <Metric label="Pending review" value={String(review.length)} hint={`${formatUsdc(sum(review))} USDC`} />
      </div>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-400">Review queue</h2>
      <Queue items={review} panel="verify" cta="Review" empty="Nothing waiting for review." />
      {release.length > 0 && (
        <>
          <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-neutral-400">Ready to release</h2>
          <Queue items={release} panel="settle" cta="Release" empty="" />
        </>
      )}
      {mine.length > 0 && (
        <>
          <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-neutral-400">Your agreements</h2>
          <div className="grid gap-4 md:grid-cols-2">{mine.map((a) => <AgreementCard key={a.id} a={a} />)}</div>
        </>
      )}
    </Layout>
  );
}

export function Worker() {
  const wallet = useStore((s) => s.wallet);
  const all = useStore((s) => s.agreements);
  if (!wallet) return <NeedWallet title="Worker" />;
  const mine = all.filter((a) => a.worker === wallet);
  const items = mine.flatMap((a) => a.milestones.map((m, i) => ({ a, m, i })));
  const of = (s: Milestone["status"]) => items.filter((x) => x.m.status === s);
  const actionable = current(mine).filter((x) => x.m.status === "PENDING");
  return (
    <Layout>
      <PageHeader title="Worker" sub="Earnings and what to do next." />
      <div className="mb-8 grid gap-4 sm:grid-cols-3">
        <Metric label="Released" value={formatUsdc(sum(of("RELEASED")))} hint="USDC received" />
        <Metric label="Verified" value={formatUsdc(sum(of("VERIFIED")))} hint="Awaiting release" />
        <Metric label="In progress" value={formatUsdc(sum([...of("PENDING"), ...of("EVIDENCE_SUBMITTED")]))} hint="USDC" />
      </div>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-400">Up next</h2>
      <Queue items={actionable} panel="evidence" cta="Submit Evidence" empty="No milestones waiting on you." />
    </Layout>
  );
}
