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

// --- where a bot looks when nothing else commands it (A1; design 6.4 "休止视线" and 6.3's work poses) ---------------------------------
// A Look is absolute (see followLook).  `restLook` answers by gaze KIND and the engine clock; null means "the pointer decides"
// (`follow`: the existing behaviour).  Kinds a persona rests on: follow, ahead-right, scan, down, front.  Kinds the work poses use:
// side (a tool is running: the aura sits on that side), below (listening to the composer / verifying: eyes on the work, constant).
const STILL = 0.35; // a little of the resting drift stays, so a held look is not a stare
const hold = (yaw, pitch) => ({ yaw, pitch, mix: 1, spin: 0, wander: STILL });
/** Seconds between two sweeps of the sentinel's scan, and between two glances up of the reader. */
export const SCAN_PERIOD = 5;
export const GLANCE_PERIOD = 6;
const SCAN_AT = [3.2, 4.1, 4.9]; // left at 3.2 s, right at 4.1 s, back to centre at 4.9 s (each held a beat)
const GLANCE_AT = [5, 5.8];      // looks up at 5 s for 0.8 s
export const LOOK_BELOW = hold(0, -11);
export const LOOK_FRONT = hold(0, PITCH);

export function restLook(kind, t = 0) {
  const time = Number.isFinite(t) ? Math.max(0, t) : 0;
  switch (kind) {
    case "ahead-right": return hold(12, PITCH - 1);
    case "side": return hold(14, PITCH - 2);
    case "below": return LOOK_BELOW;
    case "front": return LOOK_FRONT;
    case "scan": {
      const phase = time % SCAN_PERIOD;
      return phase < SCAN_AT[0] || phase >= SCAN_AT[2] ? LOOK_FRONT : phase < SCAN_AT[1] ? hold(-14, PITCH) : hold(14, PITCH);
    }
    case "down": {
      const phase = time % GLANCE_PERIOD;
      return phase >= GLANCE_AT[0] && phase < GLANCE_AT[1] ? LOOK_FRONT : LOOK_BELOW;
    }
    default: return null; // "follow", an unknown kind, or nothing: the pointer decides
  }
}

/** How far the whole body leans while it rests on this gaze, in degrees (the tracker's forward lean). */
export function restTilt(kind) { return kind === "ahead-right" ? 6 : 0; }
