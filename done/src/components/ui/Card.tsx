import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { focusRing } from "./styles";

export const Card = ({ className, ...p }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("rounded-2xl border border-line bg-surface p-5", className)} {...p} />
);
export const Nested = ({ className, ...p }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("rounded-xl border border-line-soft bg-surface-2 p-4", className)} {...p} />
);

export function Metric({ label, value, hint }: { label: string; value: string | null; hint?: string }) {
  return (
    <Card>
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</p>
      <p className="mt-2 font-mono text-2xl tabular-nums text-neutral-100">{value ?? "—"}</p>
      {hint && <p className="mt-1 text-xs text-neutral-400">{hint}</p>}
    </Card>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label, className }: {
  value: T; options: readonly { value: T; label: ReactNode }[]; onChange: (v: T) => void; label: string; className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("inline-flex max-w-full flex-wrap gap-1 rounded-xl border border-line bg-surface p-1", className)}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cn("min-h-9 rounded-lg px-3 text-sm font-medium transition-colors", focusRing,
            value === o.value ? "bg-violet-600 text-white" : "text-neutral-400 hover:text-neutral-200")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <Card className="flex flex-col items-center gap-4 py-10 text-center">
      <p className="text-sm text-neutral-400">{text}</p>
      {action}
    </Card>
  );
}

export const Skeleton = ({ className }: { className?: string }) => (
  <div className={cn("animate-pulse rounded-2xl bg-surface-2", className)} />
);
