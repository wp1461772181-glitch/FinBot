// When does a small (non-live) bot avatar need the per-frame loop?  Pure (no React, no engine, no clock of its own),
// so node --test covers it.  Design 6.2 "S tier": an idle avatar is a still frame plus a CSS breath; frames are only
// computed while something is moving the picture.
//
//   busy   = the avatar is running (orbit) or unread (notify), or its row is hovered, or the eyes are still aimed at the
//            pointer. These always want frames.
//   settle = after busy ends the engine still plays out what it was doing (state morph back to idle, the work face
//            fading to calm, the gaze easing back from the pointer). The loop keeps running until that is over, then stops.
import { ENGAGE_TIME } from "./bloub-gaze.mjs";
import { MOOD_MORPH } from "./bloub-mood.mjs";
import { T } from "./bloub-timing.mjs";

/** Seconds of frames to keep after the last busy moment: the longest of the gaze release (ENGAGE_TIME 1.1), the work
 * face fading out (MOOD_MORPH 0.8), a body-shape morph (0.45) and the longest engine state morph (orbit, 0.6 = T.DWELL),
 * plus a small margin. */
export const SETTLE = Math.max(ENGAGE_TIME, MOOD_MORPH, 0.45, T.DWELL) + 0.1;

/** Something is driving the picture right now. `state` is the avatar's engine state prop (idle / orbit / notify). */
export function frameDemand({ state, hovered = false, aiming = false }) {
  return state !== "idle" || Boolean(hovered) || Boolean(aiming);
}

/** Should the avatar be subscribed to the frame loop? `quietFor` = seconds since it was last busy (Infinity: never). */
export function needsFrames({ state, hovered = false, aiming = false, quietFor = Infinity }) {
  return frameDemand({ state, hovered, aiming }) || quietFor < SETTLE;
}
