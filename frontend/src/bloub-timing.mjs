// The director's durations (seconds), in a module of their own so that the frame-demand rules (bloub-frames.mjs, part of the first screen)
// can read them without loading the director.
/** Durations in seconds. DWELL is the engine's longest state morph (orbit, 0.6): the engine keeps ONE previous state,
 * so leaving a state sooner than that makes the fade jump instead of blend (bloub's MIN_BLOCK rule). */
export const T = {
  ATTENTION: 0.9,   // "noticed you" beat after a message is sent
  SUCCESS: 1.4,     // happy beat after an answer
  ERROR: 2.0,       // alert is cut before its "!" returns under 2 s (bloub states.ts minDuration)
  HOVER: 1.2,       // hover reaction holds this long at most, even if the pointer stays
  CLICK: 2.4,       // burst / comet are cut under 2.4 s (bloub minDuration)
  SLEEP_AFTER: 60,  // no interaction for this long -> sleep
  DWELL: 0.6,
  INTRO: 1.8,       // arrival gaze turn (1.5) + a settle beat, same shape as bloub's INTRO montage
  PARTIAL: 0.6,     // the nod of a partially succeeded turn (design 6.3: a nod, then back to idle)
  SLEEP_FREEZE: 10, // asleep this long -> a still frame, no more frames computed (design 6.9 P5)
  NUDGE: 0.9,       // a waiting-for-you `wide` lasts this long...
  NUDGE_EVERY: 6,   // ...and comes every 6 s...
  NUDGE_MAX: 3      // ...at most 3 times, then it stays still
};

