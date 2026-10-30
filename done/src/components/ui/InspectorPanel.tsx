import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Icon } from "./Icon";
import { focusRing, slide } from "./styles";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])';

/** Right sidebar (≥ md) or bottom drawer (< md). One component, one open state. */
export function InspectorPanel({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const [dragY, setDragY] = useState(0);
  const startY = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    returnTo.current = document.activeElement as HTMLElement;
    ref.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus({ preventScroll: true });
    const mobile = window.matchMedia("(max-width: 767px)").matches;
    if (mobile) document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
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
      returnTo.current?.focus?.({ preventScroll: true });
    };
  }, [open]);

  const onPointerDown = (e: PointerEvent) => { startY.current = e.clientY; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); };
  const onPointerMove = (e: PointerEvent) => { if (startY.current !== null) setDragY(Math.max(0, e.clientY - startY.current)); };
  const onPointerUp = () => { if (dragY > 80) onClose(); setDragY(0); startY.current = null; };

  return (
    <>
      <div aria-hidden onClick={onClose}
        className={cn("fixed inset-0 z-40 bg-black/60 transition-opacity md:hidden", open ? "opacity-100" : "pointer-events-none opacity-0")} />
      <aside
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        aria-hidden={!open}
        {...(!open ? { inert: "" } : {})}
        style={dragY ? { transform: `translateY(${dragY}px)` } : undefined}
        className={cn(
          "fixed z-50 overflow-y-auto border-line bg-surface p-6", slide, "transition-[transform,visibility]",
          open ? "visible" : "invisible",
          "inset-x-0 bottom-0 max-h-[85vh] rounded-t-3xl border-t pb-[calc(1.5rem+env(safe-area-inset-bottom))]",
          open ? "translate-y-0" : "translate-y-full",
          "md:inset-x-auto md:right-0 md:top-0 md:bottom-auto md:h-full md:max-h-none md:w-[440px] md:rounded-none md:rounded-l-3xl md:border-l md:border-t-0", // ui-lint-ignore: md:rounded-none only resets the mobile top radius
          open ? "md:translate-x-0" : "md:translate-x-full md:translate-y-0",
        )}
      >
        <div onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
          className="-mt-2 mb-4 flex cursor-grab touch-none justify-center py-2 md:hidden">
          <span className="h-1.5 w-10 rounded-full bg-neutral-700" />
        </div>
        <header className="mb-5 flex items-center justify-between gap-3">
          <h2 className="truncate text-base font-semibold text-neutral-100">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className={cn("rounded-xl p-2 text-neutral-400 hover:bg-surface-2", focusRing)}>
            <Icon name="x" />
          </button>
        </header>
        {open && children}
      </aside>
    </>
  );
}
