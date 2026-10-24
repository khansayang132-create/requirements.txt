# DONE components (copy-paste)

React 18+/19, TypeScript, Tailwind. No UI library needed. Put these in `components/ui/` and build every screen from them. `cn` is any class joiner (`clsx` + `tailwind-merge`, or the one-liner below).

```ts
// lib/cn.ts
export const cn = (...c: Array<string | false | null | undefined>) => c.filter(Boolean).join(" ");
```

---

## 1. Tokens

**Tailwind v4** (`app/globals.css`):

```css
@import "tailwindcss";

@theme {
  --color-surface: #0d0d0f;
  --color-surface-2: #141416;
  --color-line-soft: #202024;
  --color-line: #26262a;
  --font-sans: "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, monospace;
}

html { color-scheme: dark; background: #000; }
body { @apply bg-black text-neutral-100 font-sans antialiased; }
::selection { @apply bg-violet-600/40 text-white; }
```

**Tailwind v3** (`tailwind.config.ts`): same values under `theme.extend.colors` (`surface`, `"surface-2"`, `"line-soft"`, `line`) and `fontFamily`; keep the `html`/`body` rules in `globals.css`. Do **not** set `darkMode`; there is no light theme.

Shared class strings:

```ts
// components/ui/styles.ts
export const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500 focus-visible:ring-offset-2 focus-visible:ring-offset-black";
export const slide = "transition-transform duration-200 ease-out motion-reduce:transition-none";
```

---

## 2. Button

```tsx
// components/ui/Button.tsx
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";
import { focusRing } from "./styles";

type Variant = "primary" | "secondary" | "destructive" | "ghost";
const variants: Record<Variant, string> = {
  primary: "bg-violet-600 text-white hover:bg-violet-700 active:bg-violet-800",
  secondary: "bg-transparent border border-line text-neutral-200 hover:bg-surface-2",
  destructive: "bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20",
  ghost: "text-neutral-300 hover:bg-surface-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  pending?: boolean;
  pendingLabel?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", pending, pendingLabel = "Confirm in wallet…", disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      className={cn(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant], focusRing, className,
      )}
      {...rest}
    >
      {pending && <span className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden />}
      {pending ? pendingLabel : children}
    </button>
  );
});
```

**Destructive confirm without a dialog** (two-step, resets after 4 s):

```tsx
export function ConfirmButton({ onConfirm, children }: { onConfirm: () => void; children: React.ReactNode }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => { if (!armed) return; const t = setTimeout(() => setArmed(false), 4000); return () => clearTimeout(t); }, [armed]);
  return (
    <Button variant="destructive" onClick={() => (armed ? (setArmed(false), onConfirm()) : setArmed(true))}>
      {armed ? "Tap again to confirm" : children}
    </Button>
  );
}
```

---

## 3. Card, Metric, Segmented

```tsx
export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("rounded-2xl border border-line bg-surface p-5", className)} {...p} />
);
export const Nested = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("rounded-xl border border-line-soft bg-surface-2 p-4", className)} {...p} />
);

export function Metric({ label, value }: { label: string; value: string | null }) {
  return (
    <Card>
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</p>
      <p className="mt-2 font-mono text-2xl tabular-nums text-neutral-100">{value ?? "—"}</p>
    </Card>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }:
  { value: T; options: readonly { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-xl border border-line bg-surface p-1">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cn("min-h-9 rounded-lg px-3 text-sm font-medium transition-colors", focusRing,
            value === o.value ? "bg-violet-600 text-white" : "text-neutral-400 hover:text-neutral-200")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
```

---

## 4. StatusBadge (single source for status colors)

```tsx
// components/ui/StatusBadge.tsx
export type Status =
  | "DRAFT" | "FUNDED" | "ACTIVE" | "COMPLETED"
  | "PENDING" | "EVIDENCE_SUBMITTED" | "VERIFIED" | "RELEASED";

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

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={cn("inline-flex items-center rounded-lg px-2.5 py-1 font-mono text-xs font-medium", STYLE[status])}>
      {status.replace("_", " ")}
    </span>
  );
}
```

`Record<Status, …>` makes TypeScript fail the build if a status is added without a color.

---

## 5. InspectorPanel (right sidebar ≥ md, bottom drawer < md)

One component, one open state, so desktop and mobile never drift.

```tsx
// components/ui/InspectorPanel.tsx
"use client";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { focusRing, slide } from "./styles";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])';

export function InspectorPanel({ open, onClose, title, children }:
  { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const [dragY, setDragY] = useState(0);
  const startY = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement as HTMLElement;
    ref.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    const mobile = window.matchMedia("(max-width: 767px)").matches;
    if (mobile) document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key !== "Tab" || !ref.current) return;
      const els = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!els.length) return;
      const first = els[0], last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      returnTo.current?.focus();
    };
  }, [open, onClose]);

  const onPointerDown = (e: React.PointerEvent) => { startY.current = e.clientY; (e.target as HTMLElement).setPointerCapture(e.pointerId); };
  const onPointerMove = (e: React.PointerEvent) => { if (startY.current !== null) setDragY(Math.max(0, e.clientY - startY.current)); };
  const onPointerUp = () => { if (dragY > 80) onClose(); setDragY(0); startY.current = null; };

  return (
    <>
      {/* Mobile scrim only: tapping it closes. Desktop keeps the page usable beside the sidebar. */}
      <div aria-hidden onClick={onClose}
        className={cn("fixed inset-0 z-40 bg-black/60 transition-opacity md:hidden", open ? "opacity-100" : "pointer-events-none opacity-0")} />
      <aside
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        aria-hidden={!open}
        inert={!open || undefined}
        style={dragY ? { transform: `translateY(${dragY}px)` } : undefined}
        className={cn(
          "fixed z-50 overflow-y-auto border-line bg-surface p-6", slide,
          // mobile: bottom drawer
          "inset-x-0 bottom-0 max-h-[85vh] rounded-t-3xl border-t pb-[calc(1.5rem+env(safe-area-inset-bottom))]",
          open ? "translate-y-0" : "translate-y-full",
          // desktop: right sidebar
          "md:inset-x-auto md:right-0 md:top-0 md:bottom-auto md:h-full md:max-h-none md:w-[440px] md:rounded-none md:rounded-l-3xl md:border-l md:border-t-0", // ui-lint-ignore: md:rounded-none only resets the mobile top radius
          open ? "md:translate-x-0" : "md:translate-x-full md:translate-y-0",
        )}
      >
        <div onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
          className="-mt-2 mb-4 flex cursor-grab touch-none justify-center py-2 md:hidden">
          <span className="h-1.5 w-10 rounded-full bg-neutral-700" />
        </div>
        <header className="mb-5 flex items-center justify-between">
          <h2 className="text-base font-semibold text-neutral-100">{title}</h2>
          <button onClick={onClose} aria-label="Close" className={cn("rounded-xl p-2 text-neutral-400 hover:bg-surface-2", focusRing)}>✕</button>
        </header>
        {children}
      </aside>
    </>
  );
}
```

Drive `open` from the URL (`?inspect=…`) with `useSearchParams` + `router.replace`, so back closes the panel. While open on `lg`, add `lg:pr-[440px]` to the main column.

---

## 6. TopDrawer (global / tx alerts, replaces toasts)

```tsx
export function TopDrawer({ open, tone = "info", children, onDismiss }:
  { open: boolean; tone?: "info" | "success" | "error"; children: React.ReactNode; onDismiss: () => void }) {
  const toneCls = { info: "border-violet-500/30", success: "border-emerald-500/30", error: "border-red-500/30" }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} aria-live={tone === "error" ? "assertive" : "polite"}
      className={cn("fixed inset-x-0 top-0 z-[60] mx-auto max-w-xl px-4 pt-[env(safe-area-inset-top)]", slide,
        open ? "translate-y-0" : "-translate-y-[120%]")}>
      <div className={cn("mt-3 flex items-center gap-3 rounded-b-3xl rounded-t-xl border bg-surface p-4 text-sm text-neutral-100", toneCls)}>
        <div className="flex-1">{children}</div>
        <button onClick={onDismiss} aria-label="Dismiss" className={cn("rounded-xl p-2 text-neutral-400", focusRing)}>✕</button>
      </div>
    </div>
  );
}
```

Success alerts auto-dismiss after 6 s; errors stay until dismissed.

---

## 7. Shell and navigation

```tsx
const NAV = [
  { href: "/", label: "Overview" }, { href: "/agreements", label: "Agreements" },
  { href: "/sponsor", label: "Sponsor" }, { href: "/worker", label: "Worker" }, { href: "/settings", label: "Settings" },
] as const;
// active: pathname === href || (href !== "/" && pathname.startsWith(href))
```

- Desktop nav: `<nav className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-line bg-surface p-4 md:flex">`; item `rounded-xl px-3 py-2.5 text-sm`, active `bg-violet-600/10 text-violet-300`, else `text-neutral-400 hover:bg-surface-2 hover:text-neutral-200`; `aria-current="page"` on the active item.
- Mobile nav: `<nav className="fixed inset-x-0 bottom-0 z-30 grid h-16 grid-cols-5 rounded-t-2xl border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">`; each tab icon + 10 px label, active `text-violet-400`.
- Top bar: `h-14 border-b border-line bg-black/80 backdrop-blur` with cluster pill, RPC ping (`font-mono`, green < 300 ms, amber < 1000, red otherwise), USDC balance, wallet pill (`rounded-xl border border-line px-3 font-mono`), and `MOCK` badge (`rounded-lg bg-violet-600 px-2 py-0.5 text-xs font-bold text-white`) when mock mode is on.

---

## 8. Milestone step track

```tsx
export function StepTrack({ statuses }: { statuses: Status[] }) {
  const done = statuses.filter((s) => s === "RELEASED").length;
  return (
    <div aria-label={`${done} of ${statuses.length} settled`}>
      <div className="flex gap-1">
        {statuses.map((s, i) => (
          <span key={i} className={cn("h-1.5 flex-1 rounded-full",
            s === "RELEASED" ? "bg-violet-500" : s === "VERIFIED" ? "bg-emerald-500/60" : s === "EVIDENCE_SUBMITTED" ? "bg-yellow-500/60" : "bg-neutral-800")} />
        ))}
      </div>
      <p className="mt-1.5 font-mono text-xs text-neutral-400">{done} / {statuses.length} settled</p>
    </div>
  );
}
```
