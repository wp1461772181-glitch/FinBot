// The generalist (every bot made in the app) · small dots on a ring (design 6.5): the plainest aura, and a complete one.
// Collect: three faint dots turn slowly around the body; every tool call that brought something back lights one (a fourth, fifth and sixth
// dot join when there are more).  Check: the lit dots flash in turn.  Close: the lit dots stretch into arcs and join into one ring.  Break:
// the last dot lets go of the orbit and falls, the rest go red.  Three forms: "orbit-dots" (one orbit), "twin-dots" (two orbits, the dots
// alternating between them), "trio" (three fixed dots, bigger, that do not turn).
import { TAU, arc, closingArc, cycle, dot, endBeat, flash, lerp, normalize, polar, visibility } from "./shared.mjs";

export const TURN_PERIOD = 3.2;
const ORBIT = 1.3, BASE = 3;
const CAP = { "orbit-dots": 6, "twin-dots": 6, trio: 3 };
const PARTIAL_GAP = (36 * Math.PI) / 180;

export function orbitDots(input, form = "orbit-dots") {
  const f = CAP[form] ? form : "orbit-dots";
  const s = normalize(input, { cap: CAP[f], capM: 3 });
  if (!s.tier) return [];
  const { R, n, phase } = s, out = [], beat = endBeat(s);
  const end = phase === "done" || phase === "partial" || phase === "error";
  if (end && (beat.over || (n === 0 && phase !== "error"))) return [];
  const vis = visibility(s), fade = end ? beat.fade : 1, count = Math.max(BASE, n);
  const closing = phase === "done" || phase === "partial", failing = phase === "error";
  const gap = phase === "partial" ? PARTIAL_GAP : 0;
  const radius = 0.06 * R * (f === "trio" ? 1.5 : 1), thick = 0.045 * R;
  const turning = (phase === "tool" || phase === "answer") && f !== "trio" && !s.reduced;
  const off = turning ? (TAU * s.t) / TURN_PERIOD : 0;
  if (["think", "unread", "sleep", "offline", "cancel"].includes(phase)) return out;
  if (closing && beat.p >= 1) return n > 0 ? [arc("closed", 0, 0, ORBIT * R, 0, TAU - gap, 2, fade, { w: thick, form: gap ? "gap" : "closed" })] : [];
  const period = Math.max(1.2, n * 0.12 + 0.6);
  for (let k = 0; k < count; k++) {
    const lit = k < n, a = off + (k * TAU) / count, r = (f === "twin-dots" && k % 2 ? 1.18 : ORBIT) * R;
    if (closing && lit) {
      const [c, hw] = closingArc(k, n, a, radius / r, beat.p, gap);
      out.push(arc(`dot-${k}`, 0, 0, r, c - hw, c + hw, 2, fade, { w: thick, unit: k }));
      continue;
    }
    let o = (lit ? lerp(0.4, 1, s.arrived(k)) : 0.7) * vis * fade, tone = lit ? 2 : 0, rad = radius * (lit ? lerp(1.6, 1, s.arrived(k)) : 1), [x, y] = polar(r, a);
    if (phase === "verify" && lit && s.full) rad *= 1 + 0.7 * flash(cycle(s.t, period) * period, k * 0.12, 0.2);
    if (closing) o *= 1 - beat.p;
    if (failing) {
      tone = lit ? "danger" : 0;
      if (k === count - 1) { y += beat.p * beat.p * 0.4 * R; o *= 1 - beat.p; } // the last dot lets go and falls
    }
    out.push(dot(`dot-${k}`, x, y, rad, tone, o, { ...(lit ? { unit: k } : {}), ...(failing && k === count - 1 ? { form: "broken" } : {}) }));
  }
  return out;
}
