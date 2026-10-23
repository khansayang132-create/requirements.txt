import { cn } from "@/lib/cn";
import type { MilestoneStatus } from "@/lib/protocol";

const DOT: Record<MilestoneStatus, string> = {
  RELEASED: "bg-violet-500",
  VERIFIED: "bg-emerald-500/60",
  EVIDENCE_SUBMITTED: "bg-yellow-500/60",
  PENDING: "bg-neutral-800",
};

export function StepTrack({ statuses }: { statuses: MilestoneStatus[] }) {
  const done = statuses.filter((s) => s === "RELEASED").length;
  return (
    <div aria-label={`${done} of ${statuses.length} settled`}>
      <div className="flex gap-1">
        {statuses.map((s, i) => <span key={i} className={cn("h-1.5 flex-1 rounded-full", DOT[s])} />)}
      </div>
      <p className="mt-1.5 font-mono text-xs text-neutral-400">{done} / {statuses.length} settled</p>
    </div>
  );
}
