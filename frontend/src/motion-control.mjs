// The changing half of motion-level.mjs / motion-store.mjs, for what is not the first screen: the reader's choice, the automatic drop after slow frames and its undo, and the
// choice made in another tab.  (Start-up only needs to read; see motion-level.mjs.)
import { LEVELS, MOTION_KEY, getMotion, refreshMotion, setMotion, setResolver, storedMotionLevel } from "./motion-store.mjs";
import { readHardware, resolveMotionLevel } from "./motion-resolve.mjs";

let runtime = false, active = false;
function resolveAll(drop) {
  if (drop !== undefined) runtime = drop;
  const was = getMotion(), el = globalThis.document?.documentElement;
  const next = resolveMotionLevel({
    stored: storedMotionLevel(), prefersReduced: globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches, hardware: readHardware(), runtimeDowngraded: runtime
  });
  if (next.level === was.level && next.source === was.source) return was;
  if (el) el.dataset.motion = next.level;
  setMotion(next);
  return next;
}
/** Complete the judgement (the device, the drop): called by whatever loads after the first screen and cares for "lite" (the live avatar, the settings).  Once. */
export function activateMotion() {
  if (active) return getMotion();
  active = true;
  setResolver(resolveAll);
  followOtherTabs();
  return resolveAll();
}

/** Save the reader's choice; null forgets it (the automatic judgement decides again). */
export function saveMotionLevel(level, storage = globalThis.localStorage) {
  try { if (LEVELS.includes(level)) storage?.setItem(MOTION_KEY, level); else if (level === null) storage?.removeItem(MOTION_KEY); } catch { /* optional preference */ }
  return storedMotionLevel(storage);
}
/** The reader picks a level (or null: back to automatic). */
export function chooseMotion(level) { saveMotionLevel(level); return refreshMotion(); }

let spent = false;
/** Slow frames were measured: "lite" for the rest of this visit (not stored).  False when something above already decided. */
export function downgradeNow() { spent = true; return refreshMotion(true).source === "auto-runtime"; }
/** The reader took the drop back: "full" again for this visit, and it is not measured a second time. */
export function revertDowngrade() { return refreshMotion(false); }
/** Whether the frame watch still has something to do this visit. */
export const canWatch = () => { const { level, source } = getMotion(); return !spent && level === "full" && source === "default"; };

let listening = false;
/** Follow the choice when it is changed in another tab (the browser's `storage` event). */
function followOtherTabs() {
  if (listening || typeof window === "undefined") return;
  listening = true;
  window.addEventListener("storage", event => { if (event.key === MOTION_KEY || event.key === null) refreshMotion(); });
}
