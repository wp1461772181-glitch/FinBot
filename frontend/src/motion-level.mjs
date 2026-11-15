// Animation strength (design 6.9 P9 / P10): "full" (every effect), "lite" (no aura, the light avatar at 30 fps, no swirl) or "off" (= reduced motion).
// The ONE place the app learns how much to move: it is written to <html data-motion> (CSS reads it) and held in motion-store.mjs (code reads it).
// This file is the start-up half and is all the first screen carries: the system's reduced-motion setting is always "off" (the page can never ask
// for more), else the level the reader chose in this browser, else "full".  The judgement of the device and the drop after slow frames
// (motion-resolve.mjs, pure) join in when the live avatar or the settings page loads (motion-control.mjs).  Never stored: the automatic parts.
import { LEVELS, MOTION_KEY, setMotion, setResolver, storedMotionLevel } from "./motion-store.mjs";
export { LEVELS, MOTION_KEY, storedMotionLevel };
const REDUCED = "(prefers-reduced-motion: reduce)";

export function startMotion() {
  const query = globalThis.matchMedia?.(REDUCED), el = globalThis.document.documentElement;
  const quick = () => {
    const stored = storedMotionLevel(), next = query?.matches ? { level: "off", source: "system" } : stored ? { level: stored, source: "user" } : { level: "full", source: "default" };
    el.dataset.motion = next.level;
    setMotion(next);
    return next;
  };
  setResolver(quick);
  query?.addEventListener?.("change", () => quick());
  return quick();
}
