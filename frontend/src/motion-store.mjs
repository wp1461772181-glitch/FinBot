// What the page knows about the level of animation right now, and who is listening (design 6.9).  Everything that moves reads it from here; the
// resolver that decides it (motion-level.mjs) is needed once, at start-up, and is not imported by anything else, so the first screen carries it once.
export const MOTION_KEY = "market-evidence-agent:motion:v1";
export const LEVELS = ["full", "lite", "off"];
/** The level the reader chose in this browser, or null. */
export function storedMotionLevel(storage = globalThis.localStorage) {
  try { const value = storage?.getItem(MOTION_KEY); return LEVELS.includes(value) ? value : null; } catch { return null; }
}
let current = { level: "full", source: "default" };
let resolver = () => current;
const listeners = new Set();
export const getMotion = () => current;
/** True at "off": the same thing the system's reduced-motion setting means. */
export const motionOff = () => current.level === "off";
export const subscribeMotion = fn => (listeners.add(fn), () => listeners.delete(fn));
/** The resolver announces what it decided. */
export function setMotion(next) { current = next; listeners.forEach(fn => fn()); }
/** Decide again (`drop`: true / false sets / clears the drop after slow frames; see motion-control.mjs). */
export const refreshMotion = drop => resolver(drop);
export const setResolver = fn => { resolver = fn; };
