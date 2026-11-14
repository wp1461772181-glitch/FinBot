// ReportBot (reader) · page lines (design 6.5): on the right of the body, four lines of different lengths, a page of text in miniature.
// Collect: the lines fill from left to right one after the other (0.5 s each); every tool call that brought something back puts a small
// square margin mark beside its line (four to a page; a fifth turns the page: the old one slides up and fades, a new one comes in).
// Check: a tick is drawn at the end of each marked line, one after another, 120 ms apart: the plainest "checking the evidence" of all.
// Output: a short underline moves down the lines one by one, like a finger reading.  Close: the four lines slide to the middle and become
// one thick line, a beat, fade.  Partial: that line has a gap.  Break: one line is cut in the middle (data missing).
// Three forms (only the shape of a unit changes): "page-lines", "margin-ticks" (short stubs), "underline" (equal, thin lines).
import { clamp, dot, endBeat, ease, lerp, line, normalize, path, rect, visibility } from "./shared.mjs";

const X0 = 1.15, MARK_X = 1.02, PAGE = 4;
const ROWS = [-0.45, -0.15, 0.15, 0.45], ROWS_M = [-0.3, 0, 0.3];
const FORMS = {
  "page-lines": { lens: [0.45, 0.7, 0.38, 0.58], w: 0.05 },
  "margin-ticks": { lens: [0.2, 0.2, 0.2, 0.2], w: 0.06 },
  underline: { lens: [0.7, 0.7, 0.7, 0.7], w: 0.035 }
};
export const FILL_TIME = 0.5, CHECK_GAP = 0.12;

/** A tick drawn `p` of the way (0..1): its short leg first, then the long one. */
function partialTick(x, y, size, p) {
  const a = [x - size * 0.5, y + size * 0.05], b = [x - size * 0.12, y + size * 0.42], c = [x + size * 0.5, y - size * 0.4];
  if (p <= 0) return null;
  if (p < 0.4) { const k = p / 0.4; return `M ${a[0]} ${a[1]} L ${lerp(a[0], b[0], k)} ${lerp(a[1], b[1], k)}`; }
  const k = (p - 0.4) / 0.6;
  return `M ${a[0]} ${a[1]} L ${b[0]} ${b[1]} L ${lerp(b[0], c[0], k)} ${lerp(b[1], c[1], k)}`;
}

export function pageLines(input, form = "page-lines") {
  const f = FORMS[form] ? form : "page-lines";
  const s = normalize(input, { cap: 12, capM: 3 });
  if (!s.tier) return [];
  const { R, n, phase } = s, out = [], beat = endBeat(s), rows = s.full ? PAGE : 3;
  const end = phase === "done" || phase === "partial" || phase === "error";
  if (end && (beat.over || (n === 0 && phase !== "error"))) return [];
  const vis = visibility(s), fade = end ? beat.fade : 1, { lens, w: weight } = FORMS[f];
  const closing = phase === "done" || phase === "partial", failing = phase === "error";
  const page = s.full && n > 0 ? Math.floor((n - 1) / PAGE) : 0, onPage = n - page * PAGE; // units on the page that is showing
  const turning = s.full && page > 0 ? s.age(page * PAGE) : Infinity;                   // seconds since the page was turned
  const flip = Number.isFinite(turning) && turning < 0.32 ? ease(s.easing, turning / 0.32) : 1;
  const rowY = j => (s.full ? ROWS : ROWS_M)[j] * R;
  const filled = j => (phase === "tool" && !s.reduced ? clamp((s.t - j * FILL_TIME) / FILL_TIME) : phase === "idle" || phase === "listen" ? 0 : 1);
  const underline = phase === "answer" && !s.reduced ? Math.floor(s.t / 0.6) % rows : -1;

  if (closing && beat.p >= 1) {
    const x1 = X0 * R, x2 = (X0 + 0.8) * R, mid = (x1 + x2) / 2;
    if (phase === "partial") return [line("merged-a", x1, 0, mid - 0.08 * R, 0, 2, fade, { w: 0.14 * R, form: "gap" }), line("merged-b", mid + 0.08 * R, 0, x2, 0, 2, fade, { w: 0.14 * R })];
    return [line("merged", x1, 0, x2, 0, 2, fade, { w: 0.14 * R, form: "closed" })];
  }
  const drawPage = (suffix, shift, opacity, units, counted) => {
    for (let j = 0; j < rows; j++) {
      const len = lens[j] * R, y = rowY(j) + shift * R, lit = j < units, p = filled(j);
      let o = opacity * vis * fade, x1 = X0 * R, x2 = x1 + len, yy = y, tone = 1, width = weight * R;
      if (closing) { yy = lerp(y, 0, beat.p); x2 = lerp(x2, (X0 + 0.8) * R, beat.p); width = lerp(width, 0.14 * R, beat.p); }
      const cut = failing && j === 1;
      if (failing && cut) tone = "danger";
      // the line: its faint ground, and the part that has filled in
      if (!closing || beat.p < 1) {
        if (p < 1) out.push(line(`ground-${suffix}${j}`, x1, yy, x2, yy, 0, o * 0.8, { w: width }));
        if (p > 0) {
          if (cut) { // cut in the middle: two pieces with a gap
            const mid = (x1 + x2) / 2, gap = 0.07 * R * Math.min(1, beat.p * 3);
            out.push(line(`line-${suffix}${j}`, x1, yy, mid - gap, yy, tone, o, { w: width, form: "broken" }), line(`line-${suffix}${j}b`, mid + gap, yy, x2, yy, tone, o, { w: width }));
          } else out.push(line(`line-${suffix}${j}`, x1, yy, lerp(x1, x2, p), yy, tone, o * 0.9, { w: width }));
        }
      }
      // the margin mark of a unit, and the tick that checks it
      if (lit && s.full && !closing) {
        const a = s.arrived(page * PAGE + j);
        out.push(rect(`mark-${suffix}${j}`, MARK_X * R, yy, 0.09 * R, 0.09 * R, failing && cut ? "danger" : 2, o * lerp(0.4, 1, a), { ...(counted ? { unit: page * PAGE + j } : {}) }));
        const checking = phase === "verify" ? (s.reduced ? 1 : clamp((s.t - j * CHECK_GAP) / 0.2)) : s.verified && ["answer", "hold"].includes(phase) ? 1 : 0;
        const d = partialTick(x2 + 0.1 * R, yy, 0.1 * R, checking);
        if (d && !failing) out.push(path(`check-${suffix}${j}`, d, 2, o, { w: 0.03 * R }));
      } else if (lit && !closing) out.push(dot(`mark-${suffix}${j}`, MARK_X * R, yy, 0.05 * R, failing ? "danger" : 2, o, counted ? { unit: page * PAGE + j } : {}));
    }
  };
  if (phase === "think" || phase === "unread" || phase === "sleep" || phase === "offline" || phase === "cancel") return out;
  if (flip < 1) drawPage("old", -0.5 * flip, 1 - flip, PAGE, false); // the page being turned slides up and out
  drawPage("", flip < 1 ? 0.4 * (1 - flip) : 0, flip < 1 ? flip : 1, flip < 1 ? 1 : onPage, true);
  if (underline >= 0) out.push(line("reading", X0 * R, rowY(underline) + 0.09 * R, (X0 + 0.3) * R, rowY(underline) + 0.09 * R, 2, vis, { w: 0.03 * R }));
  return out;
}
