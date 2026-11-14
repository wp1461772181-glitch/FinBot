// What every aura shares (design 6.2: the four beats; 6.9: reduced motion).  An aura is a pure function
//   aura(input) -> primitives[]
// of a state, the seconds since that state began, and the number of units (tool calls that brought something back).  No DOM, no clock,
// no random numbers: node --test covers it and the renderer (components/bot/aura-paint.ts) only draws what comes out.
//
// Geometry is in body radii: the renderer passes R (the body's radius in svg units) and every number here is a multiple of it.
// Angles are radians, 0 = twelve o'clock, clockwise.  A primitive is plain data:
//   { key, kind: "line"|"arc"|"dot"|"rect"|"path", ...geometry, w?, dash?, dashOffset?, opacity, tone, unit?, form?, anim? }
//   line  x1 y1 x2 y2        arc  cx cy r a0 a1 (a1 > a0, clockwise)       dot  cx cy r        rect  x y w h (centre based)   path  d
//   tone  0 | 1 | 2 = the bot's own colour in three steps of brightness (the thinking ring's RING_LEVELS), "ink" = the page's ink,
//         "amber" = waiting-for-you, "danger" = failure (the two semantic colours of the whole site).
//   unit  the index of the unit this primitive shows (only on the primitives of units that have come back: they are what is counted).
//   form  "closed" | "gap" | "broken": the finished shape of a turn (only on the primitive(s) that make it).
//   anim  "slow-blink": the renderer animates it with CSS (the sentinel's sleeping watch), no per-frame work.

import { TONE_LEVELS } from "./tones.mjs";

export const TAU = Math.PI * 2;
export const PHASES = ["idle", "listen", "think", "tool", "verify", "answer", "hold", "done", "partial", "error", "cancel", "unread", "sleep", "offline"];
export const TONES = [0, 1, 2, "ink", "amber", "danger"];
/** Entering a state takes at most this long (design 6.2). */
export const TRANSITION = 0.32;
/** A unit that has just come back takes this long to settle into place. */
export const ARRIVE = 0.24;
export { TONE_LEVELS };

export const clamp = (x, lo = 0, hi = 1) => (x < lo ? lo : x > hi ? hi : x);
export const lerp = (a, b, p) => a + (b - a) * p;
export const num = (x, fallback = 0) => (typeof x === "number" && Number.isFinite(x) ? x : fallback);
/** Point at radius r and angle a (0 = up, clockwise). */
export const polar = (r, a) => [r * Math.sin(a), -r * Math.cos(a)];

// ---- easing: smooth, spring (about 6% overshoot) and step (every move is made in four jumps) ------------------------------------------
const SPRING_C = 1.285; // easeOutBack constant: peak = 1 + 4c^3 / (27 (c + 1)^2) = 1.06
const EASERS = {
  smooth: x => x * x * (3 - 2 * x),
  spring: x => 1 + (SPRING_C + 1) * (x - 1) ** 3 + SPRING_C * (x - 1) ** 2,
  step: x => (x >= 1 ? 1 : Math.floor(x * 4) / 4)
};
/** Ease progress `x` (clamped to 0..1) the way the bot moves.  Unknown names are smooth. */
export function ease(kind, x) { const p = clamp(num(x)); return p <= 0 ? 0 : p >= 1 ? 1 : (EASERS[kind] ?? EASERS.smooth)(p); }
export const smooth = x => EASERS.smooth(clamp(num(x)));

// ---- primitives ----------------------------------------------------------------------------------------------------------------------
const base = (key, kind, tone, opacity, extra) => ({ key, kind, ...extra, opacity: round(clamp(num(opacity, 1))), tone });
const round = v => Math.round(v * 1000) / 1000;
const r3 = o => { for (const k of Object.keys(o)) if (typeof o[k] === "number") o[k] = round(o[k]); return o; };
/** A line from (x1,y1) to (x2,y2); `w` is the stroke width, `dash`/`dashOffset` make it dashed. */
export const line = (key, x1, y1, x2, y2, tone, opacity, extra = {}) => r3(base(key, "line", tone, opacity, { x1, y1, x2, y2, ...extra }));
/** An arc of a circle of radius r around (cx, cy), from angle a0 to a1 (clockwise, a1 >= a0). */
export const arc = (key, cx, cy, r, a0, a1, tone, opacity, extra = {}) => r3(base(key, "arc", tone, opacity, { cx, cy, r, a0, a1, ...extra }));
export const dot = (key, cx, cy, r, tone, opacity, extra = {}) => r3(base(key, "dot", tone, opacity, { cx, cy, r, ...extra }));
/** A rectangle given by its centre. */
export const rect = (key, x, y, w, h, tone, opacity, extra = {}) => r3(base(key, "rect", tone, opacity, { x, y, w, h, ...extra }));
export const path = (key, d, tone, opacity, extra = {}) => r3(base(key, "path", tone, opacity, { d, ...extra }));

// ---- the input -----------------------------------------------------------------------------------------------------------------------
/** Per-aura limits: `cap` units at tier L (M never more than `capM`). */
export function normalize(input, { cap, capM = Math.min(cap, 4) }) {
  const phase = PHASES.includes(input?.phase) ? input.phase : "idle";
  const tier = input?.tier === "M" ? "M" : input?.tier === "L" ? "L" : null;
  const reduced = Boolean(input?.reduced);
  const R = num(input?.R, 100), tempo = clamp(num(input?.tempo, 1), 0.5, 2);
  const limit = tier === "M" ? capM : cap;
  const raw = Math.max(0, Math.floor(num(input?.units)));
  // Resting and listening show no evidence: the aura is a trace of the turn that is running (or has just ended), not a log.
  const showsUnits = !["idle", "listen", "think", "cancel", "unread", "sleep", "offline"].includes(phase);
  const n = showsUnits ? Math.min(raw, limit) : 0;
  const ages = Array.isArray(input?.ages) ? input.ages : [], born = Array.isArray(input?.born) ? input.born : [];
  return {
    phase, tier, reduced, R, n, limit,
    // `t` is on the bot's own clock (the tempo already multiplied in): loops, fills and sweeps run on it.  `real` is the same moment in
    // real seconds: entering a state and the end of a turn keep to the time skeleton (design 6.2) whatever the tempo.
    t: reduced ? 0 : Math.max(0, num(input?.t)), real: reduced ? 0 : Math.max(0, num(input?.t)) / tempo, tempo, turn: reduced ? 0 : Math.max(0, num(input?.turn, num(input?.t))), easing: input?.easing ?? "smooth", settled: input?.settled ?? null,
    outcome: input?.outcome ?? null, waiting: Boolean(input?.waiting) || phase === "hold", verified: Boolean(input?.verified),
    full: tier === "L",
    /** The turn's own clock (`turn` is now on it) when unit i came back; null when unknown.  Where a scan was when it brought something. */
    born: i => (Number.isFinite(born[i]) ? born[i] : null),
    /** Seconds since unit i came back (Infinity when settled or unknown): a unit that is not new does not animate. */
    age: i => (reduced || !Number.isFinite(ages[i]) ? Infinity : Math.max(0, ages[i])),
    /** 0..1 how far unit i has arrived. */
    arrived(i) { const a = this.age(i); return a === Infinity ? 1 : smooth(a / ARRIVE); }
  };
}

/** How visible each state's aura is (the end phases fade by their own beat).  idle: "almost invisible". */
const VISIBLE = { idle: 0.5, listen: 0.5, think: 0, tool: 1, verify: 1, answer: 0.9, hold: 1, done: 1, partial: 1, error: 1, cancel: 0, unread: 0, sleep: 0, offline: 0 };
/** 0..1: the aura's overall visibility, eased from what the previous state left (`settled`) over the transition. */
export function visibility(s) {
  const now = VISIBLE[s.phase] ?? 0;
  if (s.reduced || s.phase === "cancel") return now;
  const was = s.settled ? VISIBLE[s.settled.phase] ?? 0 : now;
  return lerp(was, now, ease(s.easing, s.real / TRANSITION));
}

// ---- the end of a turn: close (or break), hold, fade ---------------------------------------------------------------------------------
/** Seconds (real) of the three parts.  done / partial: 0.32 + 0.4 + 0.4 = 1.12 <= 1.4 (T.SUCCESS); error: 0.4 + 1.3 + 0.3 = 2.0 (T.ERROR). */
export const END = {
  done: { close: 0.32, hold: 0.4, fade: 0.4 },
  partial: { close: 0.32, hold: 0.4, fade: 0.4 },
  error: { close: 0.4, hold: 1.3, fade: 0.3 }
};
export const endLength = phase => { const e = END[phase]; return e ? e.close + e.hold + e.fade : 0; };
/** Where the end beat is at `t`: `p` how far the shape has closed (or broken), `fade` the opacity left, `over` past the last moment.
 * Reduced motion: the finished shape, whole. */
export function endBeat(s) {
  const e = END[s.phase];
  if (!e) return { p: 0, fade: 1, over: false };
  if (s.reduced) return { p: 1, fade: 1, over: false };
  return { p: ease(s.easing, s.real / e.close), fade: 1 - clamp((s.real - e.close - e.hold) / e.fade), over: s.real >= endLength(s.phase) };
}

/** A repeating beat: 0..1 position inside a period of `period` seconds (the loop of a working aura; 1.2 s to 4.8 s). */
export const cycle = (t, period) => ((t % period) + period) % period / period;
/** A window inside a loop: 1 -> 0 as `t` leaves [start, start + length] (a flash). */
export const flash = (t, start, length) => { const x = (t - start) / length; return x < 0 || x > 1 ? 0 : Math.sin(Math.PI * x); };

/** Where unit i of n stands while the units close into a ring (p: 0 -> 1): from its own place (centre c0, half width hw0) to its share of the
 * circle, or of the circle minus a gap of `gap` radians (the ring that closes but not quite) that starts `start` radians after the top.  Returns [centre, half width]. */
export function closingArc(i, n, c0, hw0, p, gap = 0, start = 0) {
  const w = (TAU - gap) / Math.max(1, n);
  return [lerp(c0, start + (i + 0.5) * w, p), lerp(hw0, w / 2, p)];
}

/** The share (in body radii, from -0.9 to 0.9) that unit i of n takes of the one line a row of units merges into; `gap`: the line stops short
 * (1.5 of 1.8) and what is missing is left open.  Returns [from, to]. */
export function rowShare(i, n, gap = false) {
  const total = gap ? 1.5 : 1.8, share = total / Math.max(1, n);
  return [-0.9 + i * share, -0.9 + (i + 1) * share];
}
