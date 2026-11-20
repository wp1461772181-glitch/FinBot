import { useEffect, useRef, type RefObject } from "react";

/**
 * The phone's full-screen detail (the same node as the desktop's right column, so a window moved across the breakpoint never unmounts it): while `open`, everything
 * outside the layer cannot be reached (siblings on every level of its ancestor chain are made inert; the ancestors themselves are not), the body does not scroll, Tab
 * wraps inside the layer, Esc closes it and the focus goes to the layer's back button on opening and to `returnTo` on closing.  The materials page and the replay page share it.
 *
 * The system's Back (the phone's back gesture or button) closes the layer too: opening puts one history entry on top of the page's own (same address, a marker in its state), Back
 * pops it and closes the layer; closing any other way (the layer's 返回列表, Esc) pops that entry itself, so the reader is where they were and one more Back leaves the page rather
 * than reopening the layer.  (The browser keeps the popped entry as a forward entry; `history.length` does not shrink, nothing can make it.)  When the reader has navigated away
 * from the layer by then, the entry is not ours to pop and is left alone.
 */
export function useDetailLayer({ open, layer, back, onClose, returnTo }: { open: boolean; layer: RefObject<HTMLElement | null>; back: RefObject<HTMLElement | null>; onClose: () => void; returnTo: string }) {
  const was = useRef(false);
  const close = useRef(onClose);
  close.current = onClose;
  const pushed = useRef(false);
  useEffect(() => {
    if (!open) {
      if (was.current) document.querySelector<HTMLElement>(returnTo)?.focus();
      was.current = false;
      return;
    }
    was.current = true;
    const shut: Element[] = [];
    for (let level: HTMLElement | null = layer.current; level && level !== document.body; level = level.parentElement) {
      for (const sibling of Array.from(level.parentElement?.children ?? [])) {
        if (sibling !== level && !sibling.hasAttribute("inert")) { sibling.setAttribute("inert", ""); shut.push(sibling); }
      }
    }
    back.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // A focus in a popup of the layer (a list drawn outside it) is left alone; otherwise Tab past either end wraps inside the layer.
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) { close.current(); return; }
      const root = layer.current;
      if (event.key !== "Tab" || event.defaultPrevented || !root) return;
      const active = document.activeElement;
      if (active && active !== document.body && !root.contains(active)) return;
      const stops = Array.from(root.querySelectorAll<HTMLElement>("a[href],button,input,select,textarea,summary,[tabindex]:not([tabindex='-1'])"))
        .filter(node => !(node as HTMLButtonElement).disabled && node.getClientRects().length > 0 && !node.closest("[inert]"));
      const first = stops[0], last = stops[stops.length - 1];
      if (!first || !last) { event.preventDefault(); return; }
      const leaving = active === document.body || !root.contains(active) || (event.shiftKey ? active === first || active === root : active === last);
      if (leaving) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
    };
    window.addEventListener("keydown", onKeyDown);
    window.history.pushState({ ...(window.history.state ?? {}), detailLayer: true }, "");
    pushed.current = true;
    const onPop = () => { if (pushed.current) { pushed.current = false; close.current(); } };
    window.addEventListener("popstate", onPop);
    return () => {
      shut.forEach(node => node.removeAttribute("inert")); document.body.style.overflow = previousOverflow; window.removeEventListener("keydown", onKeyDown); window.removeEventListener("popstate", onPop);
      if (pushed.current) { pushed.current = false; if (window.history.state?.detailLayer) window.history.back(); }
    };
  }, [open, layer, back, returnTo]);
}
