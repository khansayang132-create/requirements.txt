import { forwardRef, useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
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
  { variant = "primary", pending, pendingLabel = "Confirm in wallet…", disabled, className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
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

/** Destructive confirm without a dialog: first tap arms, second tap acts, resets after 4 s. */
export function ConfirmButton({ onConfirm, children, className }: { onConfirm: () => void; children: ReactNode; className?: string }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <Button variant="destructive" className={className} onClick={() => (armed ? (setArmed(false), onConfirm()) : setArmed(true))}>
      {armed ? "Tap again to confirm" : children}
    </Button>
  );
}
