// Where the bot looks while a tool runs: toward its aura (design 6.3 "视线转向光环一侧", 6.5).  Pure; the director asks `toolGaze(variant)`,
// the renderer turns a gaze kind into a Look with `auraLook` (the kinds bloub-gaze.restLook does not know).
import { PITCH } from "../bloub-gaze.mjs";
import { TAU } from "./shared.mjs";

/** Speed lines trail on the left, page lines stand on the right, the ticker lies below: the eyes go there.  The dial, the halo, the reticle
 * and the dots turn: the eyes follow the moving point ("sweep"). */
const SIDE = { "speed-lines": "side-left", "page-lines": "side", "margin-ticks": "side", underline: "side", ticker: "below", morse: "below", beacon: "below" };
export const toolGaze = variant => SIDE[variant] ?? "sweep";

/** The seconds one lap of the moving point takes, by variant (aura files' own periods). */
export const SWEEP_PERIOD = { ticks: 1.6, gauge: 1.6, pips: 1.6, halo: 4.8, reticle: 2.4, "orbit-dots": 3.2, "twin-dots": 3.2, trio: 3.2 };
/** Where the moving point is (radians, 0 = up, clockwise): `t` seconds into the state, `turn` seconds into the turn (the reticle's scan runs on it). */
export const sweepAngle = (variant, t, turn = t) => (TAU * (variant === "reticle" ? turn : t)) / (SWEEP_PERIOD[variant] ?? 1.6);

/** The look toward a point at angle `a` (0 = up, clockwise), in eighths of a turn: a glance, not a track. */
export function sweepLook(a) {
  const q = (Math.round((a / TAU) * 8) / 8) * TAU;
  return { yaw: 14 * Math.sin(q), pitch: PITCH - 2 + 9 * Math.cos(q), mix: 1, spin: 0, wander: 0.35 };
}
