import { useEffect, useState } from "react";

/** The phone's tab bar is 3.5rem (56px) tall and sits under the page: a keyboard covers it first, so only what is above that bar needs room. */
const BAR_PX = 56;

/**
 * How far the on-screen keyboard covers the bottom of the page, for the browsers that put it OVER the layout viewport (iOS Safari; Android
 * Chrome without `interactive-widget=resizes-content`, which index.html asks for and which resizes the layout instead, leaving this at 0).
 * `visualViewport` is the part of the page that is actually visible: what is missing under it is the keyboard.  The caller pads the chat page by
 * this much, so the composer stays above the keys.  Only used on a phone; 0 everywhere else.
 */
export function useKeyboardInset(enabled: boolean): number {
  const [inset, setInset] = useState(0);
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!enabled || !viewport) { setInset(0); return; }
    const update = () => setInset(Math.max(0, Math.round(window.innerHeight - viewport.height - viewport.offsetTop - BAR_PX)));
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    update();
    return () => { viewport.removeEventListener("resize", update); viewport.removeEventListener("scroll", update); };
  }, [enabled]);
  return enabled ? inset : 0;
}
