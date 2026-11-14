// Shared by the aura tests: the input of a state with sensible defaults, and a few readers of a primitive list.
import { AURA_VARIANTS } from "../src/bot-persona.mjs";

export const R = 100;
export const input = (phase, over = {}) => ({ phase, t: 0.5, units: 3, tier: "L", R, ...over });
export const units = prims => prims.filter(p => p.unit !== undefined);
export const forms = prims => prims.map(p => p.form).filter(Boolean);
export const byKey = (prims, key) => prims.find(p => p.key === key);
export const deg = rad => (rad * 180) / Math.PI;
/** Angle (degrees, 0 = up, clockwise, 0..360) of a point relative to the centre. */
export const angleOf = (x, y) => (deg(Math.atan2(x, -y)) + 360) % 360;
export const centre = p => {
  if (p.kind === "line") return [(p.x1 + p.x2) / 2, (p.y1 + p.y2) / 2];
  if (p.kind === "arc") { const a = (p.a0 + p.a1) / 2; return [p.cx + p.r * Math.sin(a), p.cy - p.r * Math.cos(a)]; } // the middle of the arc
  return [p.cx ?? p.x, p.cy ?? p.y];
};
/** Every variant of every archetype, flat: [archetype, variant]. */
export const VARIANTS = Object.entries(AURA_VARIANTS).flatMap(([arch, list]) => list.map(variant => [arch, variant]));
export const PHASES = ["idle", "listen", "think", "tool", "verify", "answer", "hold", "done", "partial", "error", "cancel", "unread", "sleep", "offline"];
