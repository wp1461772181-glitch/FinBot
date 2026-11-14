// NewsBot (sentinel) · the news ticker and the signal arcs (design 6.5): a row of five short bars 1.35 R below the body, like the headlines of
// a page in miniature, and two concentric arcs at the upper right, like a signal sign.  Everything moves in STEPS (a telegraph, a news crawl).
// Think: the two arcs light in turn, sending.  Collect: the bars crawl from right to left, one slot at a time; every tool call that brought
// something back "cuts" one bar: it turns solid and parks at the far left (at most five).  Check: a small dot lights above each parked bar in
// turn.  Output: the crawl goes on, the arcs are out.  Wait: the crawl stops, the arcs stay lit.  Close: the parked bars press into one thick
// line, which flashes for one step and fades.  Break: the outer arc goes out and the bars drop one after another.  Unread: the arcs flash
// twice.  Sleep: the arcs keep watch, a slow blink the renderer does with CSS (this only marks them).
// Three forms (only the unit changes): "ticker" (bars of different lengths), "morse" (dashes and dots), "beacon" (round dots on a shallow curve).
import { arc, clamp, dot, endBeat, ease, lerp, line, normalize, rowShare, visibility } from "./shared.mjs";

const SLOTS_L = 5, SLOTS_M = 3;
const PITCH = 0.46, Y = 1.35;
/** Lengths of the five bars in R (a dash is long, a dot has none: it is drawn round). */
const LENGTHS = { ticker: [0.34, 0.2, 0.3, 0.14, 0.26], morse: [0.3, 0, 0.3, 0, 0.3], beacon: [0, 0, 0, 0, 0] };
export const CRAWL_RATE = 3; // steps per second
const ARC_AT = [0.62, -0.62], ARC_R = [0.4, 0.66], ARC_SPAN = [(20 * Math.PI) / 180, (70 * Math.PI) / 180];
const ARC_DIM = 0.55;

/** Everything in this aura is stepped: a continuous value is shown in quarters. */
const quant = v => Math.ceil(v * 4 - 1e-9) / 4;

export function ticker(input, form = "ticker") {
  const f = LENGTHS[form] ? form : "ticker";
  const s = normalize(input, { cap: SLOTS_L, capM: SLOTS_M });
  if (!s.tier) return [];
  const { R, n, phase } = s, slots = s.full ? SLOTS_L : SLOTS_M, out = [], beat = endBeat(s);
  const end = phase === "done" || phase === "partial" || phase === "error";
  if (end && beat.over) return [];
  const vis = visibility(s), fade = end ? quant(beat.fade) : 1;
  const closing = phase === "done" || phase === "partial", failing = phase === "error";
  const tone = failing ? "danger" : 2;
  const x = slot => (slot - (slots - 1) / 2) * PITCH * R;
  const barY = slot => (f === "beacon" ? Y - 0.06 * (slot - (slots - 1) / 2) ** 2 / 2 : Y) * R;
  const bar = (key, x0, y0, len, w, t, o, extra) => (len > 0 ? line(key, x0 - len / 2, y0, x0 + len / 2, y0, t, o, { w, ...extra }) : dot(key, x0, y0, w * (f === "beacon" ? 0.85 : 0.55), t, o, extra));

  // the signal arcs
  const arcs = (lit, t0 = tone) => ARC_R.forEach((r, k) => {
    const on = lit[k], cx = ARC_AT[0] * R, cy = ARC_AT[1] * R;
    if (on === null) return;
    out.push(arc(`arc-${k}`, cx, cy, r * R, ARC_SPAN[0], ARC_SPAN[1], on ? t0 : 0, (on ? 1 : ARC_DIM) * vis * fade, { w: 0.06 * R, ...(failing && k === 0 ? { form: "broken" } : {}) }));
  });
  const tt = s.t;
  switch (phase) {
    case "think": arcs(s.reduced ? [true, true] : Math.floor(tt / 0.5) % 2 === 0 ? [true, false] : [false, true], 2); break;
    case "unread": if (!s.reduced && tt < 0.6 && Math.floor(tt / 0.2) % 2 === 0) arcs([true, true], 2); else if (s.reduced) arcs([true, true], 2); break;
    case "sleep": ARC_R.forEach((r, k) => out.push(arc(`arc-${k}`, ARC_AT[0] * R, ARC_AT[1] * R, r * R, ARC_SPAN[0], ARC_SPAN[1], 1, 0.5, { w: 0.06 * R, anim: "slow-blink" }))); return out;
    case "hold": arcs([true, true], 2); break;
    case "answer": case "done": case "partial": break;
    case "error": arcs([true, null]); break;
    case "idle": case "listen": case "tool": case "verify": arcs([false, false]); break;
    default: break;
  }
  if (["think", "unread", "cancel", "offline"].includes(phase)) return out;

  // the bars: parked (one per unit, at the left) and crawling (in the slots that are left)
  const free = slots - n, step = phase === "tool" || phase === "answer" ? Math.floor(s.t * CRAWL_RATE) : 0;
  const drop = i => (failing ? clamp((s.real - 0.1 - 0.18 * i) / 0.4) : 0);
  for (let i = 0; i < slots; i++) {
    const parked = i < n, slot = parked ? i : n + (((i - n - step) % free) + free) % free;
    const len = LENGTHS[f][i % 5] * R, w = 0.07 * R, a = parked ? s.arrived(i) : 1;
    let x0 = x(slot), y0 = barY(slot), o = (parked ? lerp(0.5, 1, a) : 0.9), t = parked ? 2 : 1, width = w, length = len, fall = drop(i);
    if (failing) { t = "danger"; y0 += ease(s.easing, fall) * 0.7 * R; o *= 1 - ease(s.easing, fall); }
    if (closing) {
      if (!parked) o *= 1 - quant(beat.p);
      else {
        const [from, to] = rowShare(i, n, phase === "partial"), mid = ((from + to) / 2) * R;
        x0 = lerp(x0, mid, beat.p); length = lerp(len, (to - from) * R, beat.p); width = lerp(w, 0.14 * R, beat.p);
      }
    }
    if (closing && beat.p >= 1) continue;
    if (o * vis * fade < 0.004) continue;
    out.push(bar(`bar-${i}`, x0, y0, length, width, t, o * vis * fade, parked ? { unit: i } : {}));
    // the check: a small dot above a parked bar (the whole row once the check is over, in the states after it)
    if (parked && s.full && !closing && !failing && (phase === "verify" ? s.reduced || s.t >= 0.2 * i : s.verified && ["answer", "hold"].includes(phase))) {
      out.push(dot(`chk-${i}`, x0, y0 - 0.2 * R, 0.04 * R, 2, vis * fade));
    }
  }
  if (closing && beat.p >= 1 && n > 0) {
    const [from, to] = rowShare(0, 1, phase === "partial"), flash = s.real < 0.32 + 0.12 && !s.reduced;
    out.push(line("merged", from * R, Y * R, to * R, Y * R, 2, fade, { w: 0.14 * R * (flash ? 1.4 : 1), form: phase === "partial" ? "gap" : "closed" }));
    if (phase === "partial") out.push(dot("gap-end", 0.9 * R, Y * R, 0.05 * R, 0, fade));
  }
  return out;
}
