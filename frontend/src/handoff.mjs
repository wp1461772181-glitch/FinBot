// The handoff (design 6.7): what happens when the reader switches bot.  Pure: the timeline, the direction of a slide, who gets the focus,
// which messages fade in.  One rule above all: CONTENT DOES NOT WAIT FOR ANIMATION: the new line is mounted and typeable at once; every number
// here only times what plays around it.

/** The timeline in seconds after the switch was asked for (the click).  The avatar's tail may run longer than the content (SWIRL_END). */
export const HANDOFF = {
  /** The old line fades and rises 4px; the old aura plays its leave. */
  OUT: 0.12,
  /** The avatar swaps: the new silhouette, the new colour (COLOR seconds), the swirl.  The old aura has left by now. */
  SWAP: 0.12,
  COLOR: 0.24,
  /** The new aura's enter (at most 400 ms) starts here and the swirl rings go at SWIRL_END. */
  ENTER_AT: 0.42,
  ENTER: 0.4,
  SWIRL_END: 1.28,
  /** The last three messages of the new line fade in, 20 ms apart, from this moment. */
  STAGGER_FROM: 0.16,
  STAGGER_STEP: 0.02,
  STAGGER_COUNT: 3,
  /** The composer gets the focus when the new line has mounted, not later than this (a pointer / drawer switch only). */
  FOCUS_BY: 0.3,
  /** After settling on a bot with unread messages the eyes look at the divider this long. */
  GLANCE: 0.8,
  /** Reduced motion and the "off" level: the old and new line cross-fade this long, nothing else moves. */
  CROSSFADE: 0.15,
  /** The phone slides the line sideways this far (px). */
  SLIDE_PX: 24,
  /** Switches closer together than this are one gesture: the avatar goes straight to the last target. */
  RAPID: 0.3,
  /** A switch that was asked for and never came (the address did not change): the avatar goes back to what it was after this long. */
  NEVER: 1.2
};

/** Which way a phone's line slides: +1 when the target is further down the list than where we came from (it comes in from the right), -1 up, 0 unknown. */
export function handoffDirection(order, fromId, toId) {
  if (!Array.isArray(order) || fromId === toId) return 0;
  const a = order.indexOf(fromId), b = order.indexOf(toId);
  if (a < 0 || b < 0) return 0;
  return b > a ? 1 : -1;
}

/** Where a switch came from: a pointer click on a row, a choice in the phone's drawer, the keyboard (Enter on a row), or the address (back button, a link). */
export const SOURCES = ["pointer", "drawer", "keyboard", "route"];
export function sourceOfClick(detail, inDrawer = false) {
  if (inDrawer) return "drawer";
  return Number(detail) > 0 ? "pointer" : "keyboard";
}

/** The composer takes the focus after a switch the reader made with the pointer (or a drawer): somebody who is walking the sidebar with the keyboard,
 * or arrived by the address, keeps the focus where it is. */
export const movesFocus = source => source === "pointer" || source === "drawer";
