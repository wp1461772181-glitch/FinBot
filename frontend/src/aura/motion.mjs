// The small movements of the body that belong to an aura's grammar (design 6.5), as numbers for the renderer to apply as a transform
// (the engine is not touched).  Pure.  Only two bots have any: TeslaBot (speed lines) darts right 0.12 R when a tool starts or brings
// something back, brakes past upright by 2 degrees when it is done and leans back 6 degrees when it fails; AppleBot (halo) settles from
// 1.04 times its size to 1 when it is done.
import { clamp, ease } from "./shared.mjs";

/** Out 160 ms, back 240 ms: 0 -> 1 -> 0 over 0.4 s. */
export function dart(age) {
  if (!(age >= 0) || age >= 0.4) return 0;
  return age < 0.16 ? ease("smooth", age / 0.16) : 1 - ease("smooth", (age - 0.16) / 0.24);
}

export const REST = Object.freeze({ dx: 0, tilt: 0, scale: 1 });

/** `dx` in body radii (right is positive), `tilt` in degrees (forward / right is positive), `scale` about the centre.
 * `real` is the seconds since the state began in real time; `ages` the real seconds since each unit came back. */
export function bodyMotion({ variant, phase, real = 0, ages = [], reduced = false }) {
  if (variant === "speed-lines") {
    if (phase === "error") return { dx: 0, tilt: -6 * (reduced ? 1 : ease("smooth", real / 0.2)) || 0, scale: 1 };
    if (reduced) return REST;
    if (phase === "tool") { const since = Math.min(real, ...ages.filter(Number.isFinite)); return { dx: 0.12 * dart(since), tilt: 0, scale: 1 }; }
    if (phase === "done") return { dx: 0, tilt: -2 * Math.sin(Math.PI * clamp(real / 0.5)) || 0, scale: 1 }; // the brake: past upright, then settled
    return REST;
  }
  if (variant === "halo" && !reduced && (phase === "done" || phase === "partial")) return { dx: 0, tilt: 0, scale: 1 + 0.04 * (1 - ease("smooth", real / 0.32)) };
  return REST;
}
