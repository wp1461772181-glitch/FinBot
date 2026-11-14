// FinBot (lead) · the evidence dial (design 6.5): a ring of short ticks 1.28 R from the centre, like the face of a gauge.
// Collect: a bright point sweeps the ring clockwise (1.6 s a lap) and every tool call that brought something back lights the next tick.
// Check: the lit ticks flash in turn, 80 ms apart.  Close: the lit ticks grow along the circle until they meet: one whole ring.
// Break: the ring opens at the bottom and the ticks on both sides of the gap fall and fade.
// Three forms of the same grammar (only the shape and the layout of a unit change): "ticks" (twelve radial ticks), "gauge" (ten short arcs
// along three quarters of a circle) and "pips" (twelve dots).  Tier M has fewer slots and none of the finer motion.
import { TAU, arc, closingArc, cycle, dot, endBeat, flash, lerp, line, normalize, polar, visibility } from "./shared.mjs";

export const SWEEP_PERIOD = 1.6;
/** Slots of each form by tier; a unit takes one slot (never more units than slots). */
export const SLOTS = { ticks: { L: 12, M: 8 }, gauge: { L: 10, M: 6 }, pips: { L: 12, M: 8 } };
const RING = 1.28;
const MAX_M = 5;
const slotAngle = (form, k, slots) => (form === "gauge" ? -0.75 * Math.PI + (k * 1.5 * Math.PI) / (slots - 1) : (k * TAU) / slots);
/** Slots that give way when the ring breaks: the one at the bottom and its neighbours (the two ends of a gauge). */
const breaks = (form, slots) => (form === "gauge" ? [0, slots - 1] : [slots / 2 - 1, slots / 2, slots / 2 + 1]);

export function ticks(input, form = "ticks") {
  const f = SLOTS[form] ? form : "ticks";
  const tier = input?.tier === "M" ? "M" : "L";
  const slots = SLOTS[f][tier];
  const s = normalize(input, { cap: SLOTS[f].L, capM: Math.min(MAX_M, SLOTS[f].M) });
  if (!s.tier) return [];
  const { R, n, phase } = s, vis = visibility(s), out = [];
  const end = phase === "done" || phase === "partial" || phase === "error";
  const beat = endBeat(s), fade = end ? beat.fade : 1;
  if (end && (beat.over || (n === 0 && phase !== "error"))) return [];
  const breath = phase === "answer" && s.full && !s.reduced ? 1 + 0.012 * Math.sin((TAU * s.t) / 2.5) : 1;
  const r = RING * R * breath, len = (f === "pips" ? 0.07 : 0.14) * R, thick = (f === "gauge" ? 0.06 : 0.045) * R;
  const verifyCycle = Math.max(1.6, n * 0.08 + 0.5);
  const gone = end && phase === "error" ? breaks(f, slots) : [];
  const closing = (phase === "done" || phase === "partial") && beat.p > 0;
  const gap = phase === "partial" ? (36 * Math.PI) / 180 : 0;
  // the finished ring: one primitive, the end of the closing
  if (closing && beat.p >= 1) {
    return [arc("closed", 0, 0, r, 0, TAU - gap, 2, fade, { w: thick, form: gap ? "gap" : "closed" })];
  }
  for (let k = 0; k < slots; k++) {
    const a = slotAngle(f, k, slots), lit = k < n, pop = lit ? s.arrived(k) : 0;
    let o = lit ? lerp(0.4, 1, pop) : 1, tone = lit ? 2 : 0, scale = lit ? lerp(1.6, 1, pop) : 1, dy = 0;
    if (phase === "verify" && lit && s.full) scale *= 1 + 0.6 * flash(cycle(s.t, verifyCycle) * verifyCycle, k * 0.08, 0.16);
    if (end) {
      if (closing) { if (lit) continue; o *= 1 - beat.p; }                         // the units become arcs below; the unlit ticks leave
      if (phase === "error") {
        if (gone.includes(k)) {
          if (k === slots / 2 && f !== "gauge") continue;                          // the bottom tick is simply gone
          dy = beat.p * beat.p * 0.3 * R; o *= 1 - beat.p;                           // its neighbours fall and fade
        } else if (lit) tone = "danger";
      }
    }
    o *= vis * fade;
    if (o <= 0.004) continue;
    const key = `slot-${k}`, [x, y] = polar(r, a), common = { ...(lit ? { unit: k } : {}) };
    if (f === "pips") out.push(dot(key, x, y + dy, len * scale, tone, o, common));
    else if (f === "gauge") out.push(arc(key, 0, dy, r, a - 0.1 * scale, a + 0.1 * scale, tone, o, { w: thick, ...common }));
    else { const [x1, y1] = polar(r - (len * scale) / 2, a), [x2, y2] = polar(r + (len * scale) / 2, a); out.push(line(key, x1, y1 + dy, x2, y2 + dy, tone, o, { w: thick, ...common })); }
  }
  if (closing) {
    // the lit ticks stretch along the circle and meet
    for (let i = 0; i < n; i++) {
      const [c, hw] = closingArc(i, n, slotAngle(f, i, slots), 0.012, beat.p, gap);
      out.push(arc(`slot-${i}`, 0, 0, r, c - hw, c + hw, 2, fade, { w: thick, unit: i }));
    }
  }
  if (phase === "error" && out[0]) out[0] = { ...out[0], form: "broken" }; // the ring that opened at the bottom
  if (phase === "tool" && !s.reduced) {
    const [x, y] = polar(r, (TAU * s.t) / SWEEP_PERIOD);
    out.push(dot("sweep", x, y, 0.06 * R, 2, vis));
  }
  return out;
}
