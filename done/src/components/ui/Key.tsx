import { useState } from "react";
import { cn } from "@/lib/cn";
import { short } from "@/lib/wallet";
import { Icon } from "./Icon";
import { focusRing } from "./styles";

/** Truncated key or hash in mono, full value in title, with a copy button. */
export function Key({ value, className, full }: { value: string; className?: string; full?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ }
  };
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1 font-mono text-xs text-neutral-300", className)} title={value}>
      <span className={full ? "break-all" : "truncate"}>{full ? value : short(value)}</span>
      <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); copy(); }} aria-label={copied ? "Copied" : "Copy"}
        className={cn("-my-1 shrink-0 rounded-lg p-2 text-neutral-500 hover:text-neutral-200", focusRing)}>
        <Icon name={copied ? "check" : "copy"} className="size-3.5" />
      </button>
    </span>
  );
}
