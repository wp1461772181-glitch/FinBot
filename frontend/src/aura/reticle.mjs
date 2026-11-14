// A tracker bot of standard pace · the scanning reticle (design 6.5): a ring in four quarters, with a gap at each of the four directions.
// Collect: a scan line goes round (2.4 s a lap); every tool call that brought something back leaves a mark point on the ring where the scan
// was.  Check: the marks flash in turn.  Close: the quarters stretch until the ring is one whole circle.  Partial: a gap stays at the top.
// Break: one quarter is missing and the ring goes red.
import { TAU, arc, cycle, dot, endBeat, flash, lerp, line, normalize, polar, visibility } from "./shared.mjs";

export const SCAN_PERIOD = 2.4;
const RING = 1.3, GAP = 0.5, SEAM = (36 * Math.PI) / 180, QUARTER = Math.PI / 2;

export function reticle(input) {
  const s = normalize(input, { cap: 8, capM: 4 });
  if (!s.tier) return [];
  const { R, n, phase } = s, out = [], beat = endBeat(s);
  const end = phase === "done" || phase === "partial" || phase === "error";
  if (end && (beat.over || (n === 0 && phase !== "error"))) return [];
  if (["think", "unread", "sleep", "offline", "cancel"].includes(phase)) return out;
  const vis = visibility(s), fade = end ? beat.fade : 1, r = RING * R;
  const closing = phase === "done" || phase === "partial", failing = phase === "error", partial = phase === "partial";
  if (closing && beat.p >= 1) return n > 0 ? [arc("closed", 0, 0, r, 0, TAU - (partial ? SEAM : 0), 2, fade, { w: 0.045 * R, form: partial ? "gap" : "closed" })] : [];
  const tone = failing ? "danger" : phase === "idle" || phase === "listen" ? 0 : 1;
  const open = k => (closing ? lerp(GAP, k === 0 && partial ? SEAM : 0, beat.p) : GAP); // the gap at the start of quarter k
  for (let k = 0; k < 4; k++) {
    if (failing && k === 1) continue; // the missing quarter
    const a0 = k * QUARTER + open(k) / 2, a1 = (k + 1) * QUARTER - open((k + 1) % 4) / 2 + (k === 3 ? 0 : 0);
    out.push(arc(`quarter-${k}`, 0, 0, r, a0, a1, tone, vis * fade * (failing ? 0.8 : 1), { w: 0.045 * R, ...(failing && k === 0 ? { form: "broken" } : {}) }));
  }
  if (s.full && !closing) { // the cross-hairs in the gaps
    for (let k = 0; k < 4; k++) { const [x1, y1] = polar(r - 0.1 * R, k * QUARTER), [x2, y2] = polar(r + 0.1 * R, k * QUARTER); out.push(line(`hair-${k}`, x1, y1, x2, y2, failing ? "danger" : 1, vis * fade * 0.8, { w: 0.03 * R })); }
  }
  const period = Math.max(1.2, n * 0.12 + 0.6);
  for (let i = 0; i < n; i++) { // a mark where the scan was when the evidence came
    const born = s.born(i), a = born === null ? (i * TAU) / Math.max(n, 4) : (TAU * born) / SCAN_PERIOD, [x, y] = polar(r, a);
    let rad = 0.06 * R * lerp(1.6, 1, s.arrived(i)), o = lerp(0.4, 1, s.arrived(i)) * vis * fade;
    if (phase === "verify" && s.full) rad *= 1 + 0.7 * flash(cycle(s.t, period) * period, i * 0.12, 0.2);
    if (closing) o *= 1 - beat.p;
    out.push(dot(`mark-${i}`, x, y, rad, failing ? "danger" : 2, o, { unit: i }));
  }
  if (phase === "tool" && !s.reduced) {
    const a = (TAU * s.turn) / SCAN_PERIOD, [x1, y1] = polar(r - 0.18 * R, a), [x2, y2] = polar(r + 0.18 * R, a);
    out.push(line("scan", x1, y1, x2, y2, 2, vis, { w: 0.04 * R }));
  }
  return out;
}
