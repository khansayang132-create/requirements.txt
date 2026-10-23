import { cn } from "@/lib/cn";
import type { AgreementStatus, MilestoneStatus } from "@/lib/protocol";

export type Status = AgreementStatus | MilestoneStatus;

const STYLE: Record<Status, string> = {
  DRAFT: "bg-neutral-800 text-neutral-300",
  PENDING: "bg-neutral-800 text-neutral-300",
  FUNDED: "bg-amber-500/10 text-amber-400 border border-amber-500/20",
  ACTIVE: "bg-amber-500/10 text-amber-400 border border-amber-500/20",
  EVIDENCE_SUBMITTED: "bg-yellow-500/10 text-yellow-300 border border-yellow-500/20",
  VERIFIED: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
  RELEASED: "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20",
  COMPLETED: "bg-violet-500/10 text-violet-300 border border-violet-500/30",
};

export function StatusBadge({ status, className }: { status: Status; className?: string }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center whitespace-nowrap rounded-lg px-2.5 py-1 font-mono text-xs font-medium", STYLE[status], className)}>
      {status.replace("_", " ")}
    </span>
  );
}
