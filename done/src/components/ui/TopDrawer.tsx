import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Icon } from "./Icon";
import { focusRing, slide } from "./styles";

type Tone = "info" | "success" | "error";
interface Alert { id: number; tone: Tone; body: ReactNode }

// One global alert at a time; newest wins. Replaces toasts.
let current: Alert | null = null;
let nextId = 1;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
export function notify(tone: Tone, body: ReactNode) { current = { id: nextId++, tone, body }; emit(); }
export function dismiss() { current = null; emit(); }

export function TopDrawer() {
  const alert = useSyncExternalStore((f) => (subs.add(f), () => subs.delete(f)), () => current);
  useEffect(() => {
    if (!alert || alert.tone === "error") return;
    const id = alert.id;
    const t = setTimeout(() => { if (current?.id === id) dismiss(); }, 6000);
    return () => clearTimeout(t);
  }, [alert]);
  const tone = alert?.tone ?? "info";
  const toneCls = { info: "border-violet-500/30", success: "border-emerald-500/30", error: "border-red-500/30" }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} aria-live={tone === "error" ? "assertive" : "polite"}
      className={cn("pointer-events-none fixed inset-x-0 top-0 z-[60] mx-auto max-w-xl px-4 pt-[env(safe-area-inset-top)]", slide,
        alert ? "translate-y-0" : "-translate-y-[120%]")}>
      {alert && (
        <div className={cn("pointer-events-auto mt-3 flex items-center gap-3 rounded-b-3xl rounded-t-xl border bg-surface p-4 text-sm text-neutral-100", toneCls)}>
          <div className="min-w-0 flex-1">{alert.body}</div>
          <button type="button" onClick={dismiss} aria-label="Dismiss" className={cn("rounded-xl p-2 text-neutral-400", focusRing)}>
            <Icon name="x" className="size-4" />
          </button>
        </div>
      )}
    </div>
  );
}
