// AppleBot (tracker, calm) · the breathing halo (design 6.5): one thin ring 1.3 R from the centre.  Nothing here overshoots or shakes.
// Collect: the ring splits into segments (one per tool call, at most five) that turn slowly; a segment that has come back is solid, the one
// still running is half transparent.  Check: the segments stop turning and line up, the gaps between them narrow.  Output: the ring is
// whole, its brightness breathing once every 2.5 s.  Close: the last gaps shut and the whole ring settles from 1.04 times its size to 1, then
// fades.  Partial: it shuts but for one gap at the top.  Break: one segment never closes, and the whole ring goes darker.
import { TAU, arc, closingArc, endBeat, ease, lerp, normalize, visibility } from "./shared.mjs";

export const TURN_PERIOD = 4.8; // seconds a lap
const GAP_OPEN = 0.28, GAP_SHUT = 0.04, GAP_JOINT = 0.03, SEAM = 0.3;
const RING = 1.3;

/** `count` segments with gaps of `gap`, the first starting `off` radians after the top; the first `litTo` are units that came back (solid),
 * the others are half transparent (a tool still running). */
function segments(out, s, count, gap, off, r, litTo, tone, opacity, extra = () => ({})) {
  const pitch = TAU / count;
  for (let i = 0; i < count; i++) {
    const lit = i < litTo, a0 = off + i * pitch + gap / 2, a1 = off + (i + 1) * pitch - gap / 2;
    out.push(arc(`seg-${i}`, 0, 0, r, a0, Math.max(a0 + 0.01, a1), lit ? tone : 1, (lit ? lerp(0.5, 1, s.arrived(i)) : 0.5) * opacity, { w: 0.05 * s.R, ...(lit ? { unit: i } : {}), ...extra(i) }));
  }
}

export function halo(input) {
  const s = normalize(input, { cap: 5, capM: 4 });
  if (!s.tier) return [];
  const { R, n, phase } = s, out = [], beat = endBeat(s);
  const end = phase === "done" || phase === "partial" || phase === "error";
  if (end && beat.over) return [];
  const vis = visibility(s), fade = end ? beat.fade : 1, r = RING * R, count = Math.max(n, 1);
  switch (phase) {
    case "idle": case "listen": out.push(arc("ring", 0, 0, r, 0, TAU, 0, vis, { w: 0.04 * R })); break;
    case "tool": {
      const total = Math.min(s.limit, n + 1);
      segments(out, s, total, GAP_OPEN, (TAU * s.t) / TURN_PERIOD, r, n, 2, vis);
      break;
    }
    case "verify": {
      // stop turning and line up (the lap so far is finished to the next joint), then the gaps narrow
      const was = s.settled?.phase === "tool" ? (TAU * (s.settled.t ?? 0)) / TURN_PERIOD : 0, pitch = TAU / count;
      const off = s.reduced ? 0 : was + ((pitch - (was % pitch)) % pitch) * ease(s.easing, s.t / 0.6);
      const gap = s.reduced ? GAP_SHUT : lerp(GAP_OPEN, GAP_SHUT, ease(s.easing, s.t / 1.2));
      segments(out, s, count, gap, off, r, n, 2, vis);
      break;
    }
    case "answer": case "hold": {
      const breathing = phase === "answer" && !s.reduced ? 0.8 + 0.2 * Math.sin((TAU * s.t) / 2.5) : 1;
      segments(out, s, count, GAP_JOINT, 0, r, n, 2, vis * breathing);
      break;
    }
    case "done": case "partial": {
      const partial = phase === "partial", scale = lerp(1.04, 1, beat.p);
      if (beat.p >= 1) { out.push(arc("closed", 0, 0, r, partial ? SEAM / 2 : 0, partial ? TAU - SEAM / 2 : TAU, 2, fade, { w: 0.05 * R, form: partial ? "gap" : "closed" })); break; }
      if (partial) { // every joint shuts except the one at the top, which opens to the seam
        for (let i = 0; i < count; i++) {
          const pitch = TAU / count, [c, hw] = closingArc(i, count, (i + 0.5) * pitch, pitch / 2 - GAP_JOINT / 2, beat.p, SEAM, SEAM / 2);
          out.push(arc(`seg-${i}`, 0, 0, r * scale, c - hw, c + hw, 2, fade, { w: 0.05 * R, ...(i < n ? { unit: i } : {}) }));
        }
      } else segments(out, s, count, lerp(GAP_JOINT, 0, beat.p), 0, r * scale, n, 2, fade);
      break;
    }
    case "error": {
      // the ring stands as it was, minus the segment that never came back, and darker
      const total = Math.max(n, 2), p = beat.p; // (the first segment carries the mark: the last one is dropped below)
      segments(out, s, total, GAP_SHUT, 0, r, n, "danger", fade * lerp(1, 0.55, p), i => (i === 0 ? { form: "broken" } : {}));
      out.pop(); // the last segment does not close
      break;
    }
    default: break;
  }
  return out;
}
