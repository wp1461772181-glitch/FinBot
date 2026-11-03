// Where the bot looks. Pure (no DOM, no engine import) so node --test covers it. Ported from bloub's UI layer
// (src/ui/gaze.ts, MIT, pinned b4bb3c1): the same Look contract (absolute yaw/pitch in degrees, `mix` = how much the
// outside world commands the direction, `wander` = remaining automatic drift, `spin` = a turn taken on the way).
// Differences from bloub: bloub parks the head turned to the left (TURN) because its panel sits there; here the bot
// faces forward, so the pointer alone decides the yaw.

/** Head orientation limits in degrees (bloub's values: wide enough to beat the resting drift, no eye behind the limb). */
export const YAW_MAX = 16;
export const PITCH_MAX = 13;
/** Eye height with the pointer level with the bot: slightly above the equator (attentive rather than absent). */
export const PITCH = 10;
/** Time for the gaze to take hold after the pointer shows up, seconds (bloub's TURN_TIME). */
export const ENGAGE_TIME = 1.1;
/** A pointer that has not moved for this long (or has left the page) stops commanding the gaze, seconds. */
export const POINTER_STALE = 2.5;
/** The arrival turn: one full turn of the eyes around the ball, then it lands (bloub's TOUR_TIME). */
export const TOUR_TIME = 1.5;
export const SPIN = 360;

const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
export const easeOutQuint = t => 1 - Math.pow(1 - clamp(t), 5);
export const easeInOutCubic = t => { const x = clamp(t); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };

/**
 * Pointer position relative to the bot, -1..1 (right / down positive), or null when there is nothing to aim at.
 * Normalised by the half-window rather than the avatar size: the gaze saturates when the pointer reaches the edge of
 * the screen. A box without area (hidden pane) gives null: the engine KEEPS its last target, so one NaN would stay.
 */
export function aimFromPointer(pointer, box, view) {
  if (!pointer || !box || !view) return null;
  if (!Number.isFinite(pointer.x) || !Number.isFinite(pointer.y)) return null;
  if (!(box.width > 0) || !(box.height > 0)) return null;
  const halfW = Math.max(1, view.width / 2), halfH = Math.max(1, view.height / 2);
  return {
    nx: clamp((pointer.x - (box.left + box.width / 2)) / halfW, -1, 1),
    ny: clamp((pointer.y - (box.top + box.height / 2)) / halfH, -1, 1)
  };
}

/** Look that follows the pointer. `engage` 0..1 ramps the takeover so the head does not snap on first contact. */
export function followLook(aim, engage = 1) {
  return { yaw: aim.nx * YAW_MAX, pitch: PITCH - aim.ny * PITCH_MAX, mix: engage, spin: 0, wander: 1 - engage };
}

/** Is the pointer still worth following? `lastMoveAt` and `now` in seconds on the same clock; null = no pointer. */
export function pointerFresh(lastMoveAt, now) {
  return lastMoveAt != null && now - lastMoveAt <= POINTER_STALE;
}

/** The arrival gaze script: mix stays 0 the whole way, only `spin` melts, so it ends where the pose commands alone. */
export function tourLook(t) {
  return { yaw: 0, pitch: 0, mix: 0, spin: SPIN * (1 - easeInOutCubic(t / TOUR_TIME)), wander: 1 };
}
