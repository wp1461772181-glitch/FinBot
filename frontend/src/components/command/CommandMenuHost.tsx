import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { COMMAND_MENU_EVENT, isPaletteShortcut } from "./command-events";
import type { PaletteData } from "./CommandMenu";

// The palette (cmdk, the dialog, the matching) is its own chunk: not part of the chat's first load.  It is fetched the first time it is
// opened, or when the browser is idle after the page has settled, so the first Cmd-K is not a wait.
const loadMenu = () => import("./CommandMenu");
const CommandMenu = lazy(loadMenu);

/**
 * Mounted once in the shell.  It listens for the shortcut and the open event, and renders the palette when asked.  The data it lists
 * (watch list, bots) is passed in: the shell already holds it.
 */
export function CommandMenuHost({ data }: { data: PaletteData }) {
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const returnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const show = (focusTarget?: HTMLElement | null) => {
      returnFocus.current = focusTarget ?? (document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null);
      setLoaded(true); setOpen(true);
    };
    const onEvent = (event: Event) => show((event as CustomEvent).detail?.returnFocus);
    const onKey = (event: KeyboardEvent) => { if (isPaletteShortcut(event)) { event.preventDefault(); if (open) setOpen(false); else show(); } };
    window.addEventListener(COMMAND_MENU_EVENT, onEvent);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener(COMMAND_MENU_EVENT, onEvent); window.removeEventListener("keydown", onKey); };
  }, [open]);
  useEffect(() => {
    const idle = (window as Window & { requestIdleCallback?: (fn: () => void, options?: { timeout: number }) => number }).requestIdleCallback;
    const warm = () => { void loadMenu(); };
    if (idle) { const id = idle(warm, { timeout: 8000 }); return () => (window as Window & { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback?.(id); }
    const timer = window.setTimeout(warm, 4000);
    return () => window.clearTimeout(timer);
  }, []);
  if (!loaded) return null;
  return <Suspense fallback={null}><CommandMenu open={open} onOpenChange={setOpen} returnFocus={returnFocus} data={data} /></Suspense>;
}
