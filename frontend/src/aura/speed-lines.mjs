// TeslaBot (tracker, fast) · speed lines (design 6.5): three short horizontal lines behind the body on the left, 0.4 R to 0.8 R long.
// Collect: the lines shoot out and flow backwards; every tool call that brought something back leaves a solid segment in the trail (at most
// five, the oldest furthest left).  Check: the solid segments light from left to right.  Output: the lines hold at six tenths and flow
// steadily.  Close: the lines draw back in and the trail joins into one line under the body, then fades.  Break: the lines turn dashed and
// droop 12 degrees (so do the trail's segments), the red holds for two seconds.
import { cycle, dot, endBeat, ease, flash, lerp, line, normalize, rowShare, visibility } from "./shared.mjs";

const SPEEDS = [0.4, 0.8, 0.55]; // lengths of the three lines, in R
const ROWS = [-0.3, 0, 0.3];
const START = -1.12;   // where the lines leave the body (x, in R)
const TRAIL_Y = 0.62, TRAIL_X = -2.25, TRAIL_STEP = 0.22, TRAIL_LEN = 0.12; // the segments leave a small gap between them (the caps are round)
const MERGE_Y = 1.18, MERGE_X = 0.9;
const DROOP = (12 * Math.PI) / 180;
export const FLOW_SPEED = 1.4; // R per second the dashes flow

/** How far the lines are out (0..1 of their length) in each state. */
const EXTENT = { idle: 0.5, listen: 0.5, think: 0, tool: 1, verify: 0.6, answer: 0.6, hold: 0, cancel: 0, unread: 0, sleep: 0, offline: 0 };

export function speedLines(input) {
  const s = normalize(input, { cap: 5, capM: 3 });
  if (!s.tier) return [];
  const { R, n, phase } = s, out = [], beat = endBeat(s);
  const end = phase === "done" || phase === "partial" || phase === "error";
  if (end && beat.over) return [];
  const vis = visibility(s), fade = end ? beat.fade : 1;
  // how far out the lines are: eased from where the previous state left them
  const was = s.settled ? EXTENT[s.settled.phase] ?? 0.6 : EXTENT[phase] ?? 0;
  let ext = end ? 0.6 : s.reduced ? EXTENT[phase] ?? 0 : lerp(was, EXTENT[phase] ?? 0, ease(s.easing, s.real / 0.32));
  const closing = phase === "done" || phase === "partial";
  if (closing) ext *= 1 - beat.p;
  const failing = phase === "error";
  const tone = failing ? "danger" : 2;
  const droop = failing ? DROOP * beat.p : 0;
  const bend = (x1, y1, length) => [x1 - length * Math.cos(droop), y1 + length * Math.sin(droop)]; // the far end (left of x1) swings down
  // the flowing lines
  if (ext > 0.004) {
    SPEEDS.forEach((len, j) => {
      const length = len * ext * R, [x2, y2] = bend(START * R, ROWS[j] * R, length);
      const flow = phase === "tool" || phase === "answer" || phase === "verify" ? { dash: [0.22 * R, 0.14 * R], dashOffset: -s.t * FLOW_SPEED * R } : failing ? { dash: [0.1 * R, 0.1 * R] } : {};
      out.push(line(`flow-${j}`, START * R, ROWS[j] * R, x2, y2, failing ? tone : 1, vis * fade * (phase === "idle" || phase === "listen" ? 1 : 0.9), { w: 0.07 * R, ...flow, ...(failing && j === 0 ? { form: "broken" } : {}) }));
    });
  }
  // the trail: one solid segment per tool call that came back
  const period = Math.max(1.4, n * 0.1 + 0.6), verifyAt = cycle(s.t, period) * period;
  const merged = closing && beat.p >= 1;
  if (merged) {
    if (n > 0) {
      out.push(line("merged", rowShare(0, 1, phase === "partial")[0] * R, MERGE_Y * R, rowShare(0, 1, phase === "partial")[1] * R, MERGE_Y * R, 2, fade, { w: 0.07 * R, form: phase === "partial" ? "gap" : "closed" }));
      if (phase === "partial") out.push(dot("gap-end", MERGE_X * R, MERGE_Y * R, 0.035 * R, 0, fade));
    }
    return out;
  }
  for (let i = 0; i < n; i++) {
    const a = s.arrived(i), xs = (TRAIL_X + i * TRAIL_STEP) * R;
    let x1 = xs, y1 = TRAIL_Y * R, x2 = xs + TRAIL_LEN * R * lerp(0.25, 1, a), y2 = y1, w = 0.06 * R, o = lerp(0.4, 1, a);
    if (closing) { // slide into its share of the line under the body
      const [from, to] = rowShare(i, n, phase === "partial");
      x1 = lerp(x1, from * R, beat.p); x2 = lerp(x2, to * R, beat.p); y1 = y2 = lerp(y1, MERGE_Y * R, beat.p);
    }
    if (failing) { const len = x2 - x1; x2 = x1 + len * Math.cos(droop); y2 = y1 + len * Math.sin(droop); } // a segment points right: its far end swings down
    if (phase === "verify" && s.full) w *= 1 + 0.7 * flash(verifyAt, i * 0.1, 0.2);
    out.push(line(`trail-${i}`, x1, y1, x2, y2, tone, o * vis * fade, { w, unit: i, ...(failing ? { dash: [0.04 * R, 0.04 * R] } : {}) }));
  }
  return out;
}
