import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A small panel that opens from a button: a dropdown on a desktop (above the button: the composer sits at the bottom of the screen),
 * a bottom sheet with a scrim on a phone.  The caller owns `open`; Esc and a press outside call `onClose`, and focus goes into the
 * panel on open and back to what had it on close.  It is not a menu: the content is whatever the caller puts in (a radio list, a card).
 */
export function PopPanel({ open, onClose, label, align = "start", className, children }: { open: boolean; onClose: () => void; label: string; align?: "start" | "end"; className?: string; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    panel.current?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); close.current(); } };
    // The wrapper is the button's parent: a press on the button itself is the button's own toggle, not "outside".
    const onPointer = (event: PointerEvent) => { const host = root.current?.parentElement; if (host && !host.contains(event.target as Node)) close.current(); };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPointer);
      if (before && document.contains(before)) before.focus({ preventScroll: true });
    };
  }, [open]);
  if (!open) return <div ref={root} hidden />;
  return <div ref={root} data-slot="pop-panel-root">
    <div aria-hidden="true" className="fixed inset-0 z-overlay bg-black/30 md:hidden" onClick={onClose} />
    <div ref={panel} role="dialog" aria-label={label} tabIndex={-1} data-slot="pop-panel"
      className={cn("z-overlay border border-line bg-surface text-ink shadow-pop outline-none",
        "max-md:fixed max-md:inset-x-0 max-md:bottom-0 max-md:max-h-[70dvh] max-md:overflow-y-auto max-md:rounded-t-lg max-md:p-4 max-md:pb-[calc(1rem+env(safe-area-inset-bottom,0px))] max-md:shadow-modal",
        "md:absolute md:bottom-full md:mb-2 md:w-80 md:max-w-[calc(100vw-2rem)] md:rounded-md md:p-3",
        align === "end" ? "md:right-0" : "md:left-0", className)}>
      {children}
    </div>
  </div>;
}
