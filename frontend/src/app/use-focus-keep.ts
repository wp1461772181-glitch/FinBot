import { useEffect, useRef } from "react";

/**
 * Keeps the control that had the focus inside a dialog, by its id (or its data-testid when it has no id).  The record dialog and the new-bot dialog are a Dialog from 640px up and a Drawer below it, two different
 * element trees: a window dragged across 640px mounts the other one, whose own auto-focus would land on the first field.  The shell calls the returned function from its
 * `onOpenAutoFocus`: it focuses the kept control when that is on the page, else what `fallback` names (the first field, or the drawer itself).
 */
export function useFocusKeep(rootTestId: string) {
  const last = useRef("");
  useEffect(() => {
    const onFocus = (event: FocusEvent) => {
      const el = event.target instanceof HTMLElement ? event.target : null;
      if (!el || !el.closest(`[data-testid=${rootTestId}]`)) return;
      const testid = el.getAttribute("data-testid");
      if (el.id) last.current = `#${CSS.escape(el.id)}`; else if (testid && testid !== rootTestId) last.current = `[data-testid="${testid}"]`;
    };
    document.addEventListener("focusin", onFocus);
    return () => document.removeEventListener("focusin", onFocus);
  }, [rootTestId]);
  return (fallback: () => HTMLElement | null | undefined) => {
    const kept = last.current ? document.querySelector<HTMLElement>(last.current) : null;
    (kept ?? fallback())?.focus();
  };
}
