// The line's side of the handoff (design 6.7): how the new thread comes in.  Pure.  Kept apart from handoff.mjs (which the first screen needs) because only
// the entrance of a thread after a switch uses it, and that code is fetched shortly after the first paint (app/chat/handoff-entry.ts).
import { HANDOFF } from "./handoff.mjs";

/** Delay (seconds) of the fade-in of message `index` out of `count`: only the last STAGGER_COUNT messages animate (null = shown at once). */
export function staggerDelay(index, count, { reduced = false } = {}) {
  if (reduced || !Number.isInteger(index) || !Number.isInteger(count)) return null;
  const first = Math.max(0, count - HANDOFF.STAGGER_COUNT);
  if (index < first || index >= count) return null;
  return HANDOFF.STAGGER_FROM + (index - first) * HANDOFF.STAGGER_STEP;
}

/** A switch asked for within RAPID of the one before it replaces it (the avatar does not play the one in between). */
export const isRapid = (previousAt, at) => Number.isFinite(previousAt) && at - previousAt < HANDOFF.RAPID;

/** What the line does on the way in, by the level of motion (A5; until it exists the level is "full" unless the system asks for less):
 * "slide" (a phone, full), "rise" (full, else), "crossfade" (reduced / off), and "none" for no direction at all (a first mount). */
export function lineMotion({ reduced, level = "full", phone = false } = {}) {
  if (reduced || level === "off") return "crossfade";
  return phone ? "slide" : "rise";
}
/** Whether the avatar plays the swirl and the entrance (full only; "lite" swaps shape and colour at once). */
export const playsSwirl = ({ reduced, level = "full" } = {}) => !reduced && level === "full";
