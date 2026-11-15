// The entrance and the exit of an aura (design 6.5 "进场 / 离场", 6.7 the handoff): two more phases of every aura, `leave` (the old bot, at most 160 ms)
// and `enter` (the new bot, at most 400 ms), and the poses the body takes meanwhile.  Pure, like the rest of src/aura.
//
// Which variant does what.  Five are designed (the five existing bots); the others of the same archetype use their archetype's motion with
// their own unit shape (the rest picture of the variant is what moves), and the two without an archetype of their own use the generalist's:
//   dial     (lead: ticks, gauge, pips)   enter: the ring is drawn from a point to a whole circle, then goes (the faint ticks stay).  leave: the ring shrinks to a point.
//   speed    (tracker fast: speed-lines)  enter: slides in from the left with the lines streaming, overshoots, settles.  leave: dashes out to the right.
//   ticker   (sentinel: ticker, morse, beacon)  enter: drops from above in two steps (a bounce between), the signal arcs flash once.  leave: lifted away upward.
//   halo     (tracker calm: halo)         enter: appears softly from 0.92 times its size and half transparent.  leave: fades.
//   page     (reader: page-lines, margin-ticks, underline)  enter: turns in about its left edge like a page.  leave: turns out the same way backwards.
//   dots     (generalist: orbit-dots, twin-dots, trio)  enter: three dots gather from outside onto the orbit.  leave: they scatter outward.
//   reticle  (tracker standard)           the plainest, as the generalist's: the four quarters gather onto the ring / scatter off it.
// Under reduced motion (and the "off" level) there is no entrance and no exit: the aura functions return nothing for these two phases.
import { HANDOFF } from "../handoff.mjs";
import { TAU, arc, clamp, dot, ease, lerp, line, num, polar, smooth } from "./shared.mjs";

export const LEAVE_LEN = HANDOFF.OUT;
export const ENTER_LEN = HANDOFF.ENTER;
export const isHandoffPhase = phase => phase === "enter" || phase === "leave";

const FAMILY = {
  ticks: "dial", gauge: "dial", pips: "dial", "speed-lines": "speed", halo: "halo", reticle: "reticle", ticker: "ticker", morse: "ticker", beacon: "ticker",
  "page-lines": "page", "margin-ticks": "page", underline: "page", "orbit-dots": "dots", "twin-dots": "dots", trio: "dots"
};
export const familyOf = variant => FAMILY[variant] ?? "dots";

// ---- the body --------------------------------------------------------------------------------------------------------------------------------
/** dx, dy in body radii; tilt in degrees; scale about the centre; sx = squash across the body about its LEFT edge (the page turn); alpha = the body's opacity. */
const REST = Object.freeze({ dx: 0, dy: 0, tilt: 0, scale: 1, sx: 1, alpha: 1 });
/** Where a body is when it has half left (the exit pose) and where the next one starts (the start pose); the poses are small on purpose: the swirl
 * and the new silhouette happen in between and carry the change, these only say whose it is. */
const POSES = {
  dial: { exit: {}, start: {} },
  speed: { exit: { dx: 0.5, alpha: 0.6 }, start: { dx: -0.5, alpha: 0.6 } },
  ticker: { exit: { dy: -0.5, alpha: 0.6 }, start: { dy: -0.6, alpha: 0.6 } },
  halo: { exit: { scale: 0.96, alpha: 0.5 }, start: { scale: 0.92, alpha: 0.5 } },
  page: { exit: { sx: 0.35, alpha: 0.8 }, start: { sx: 0.2, alpha: 0.8 } },
  dots: { exit: { scale: 0.94, alpha: 0.7 }, start: { scale: 0.9, alpha: 0.7 } },
  reticle: { exit: { scale: 0.94, alpha: 0.7 }, start: { scale: 0.9, alpha: 0.7 } }
};
const pose = (family, which) => ({ ...REST, ...(POSES[family]?.[which] ?? {}) });
const mix = (a, b, k) => { const out = {}; for (const key of Object.keys(REST)) out[key] = lerp(a[key], b[key], k); return out; };
/** The drop of the sentinel in two steps: it falls, bounces up a little, falls again (a step is a jump, there is no in-between). */
const drop = x => (x < 0.2 ? 0 : x < 0.45 ? 1 : x < 0.7 ? 0.72 : 1);
/** How the new body comes to rest, by family (6.5: TeslaBot overshoots and settles, NewsBot steps, the rest are smooth). */
const arrival = (family, x) => (family === "speed" ? ease("spring", x) : family === "ticker" ? drop(clamp(x)) : smooth(x));

/**
 * The pose of the body `age` real seconds after the switch was asked for: the old bot half leaves (0 to OUT), the pose carries over to the new
 * bot's start pose while the swirl and the new silhouette take over (to ENTER_AT), then the new bot arrives and comes to rest (ENTER long).
 * `from` / `to` are aura variants; before the swap `to` does not matter.  `quiet`: the new bot is working already, there is no entrance (the body
 * comes back to rest).  `carry`: the pose a redirected handoff takes over from (the one in between is never shown).  Reduced motion never asks.
 */
export function handoffBody({ from, to, age, quiet = false, carry = null }) {
  const a = Math.max(0, num(age)), f = familyOf(from), t = familyOf(to);
  const exit = carry ? { ...REST, ...carry } : pose(f, "exit");
  if (to == null && a >= HANDOFF.OUT) return exit; // the one that comes is not known yet: the body waits where the exit left it
  if (a < HANDOFF.OUT) return mix(carry ? { ...REST, ...carry } : REST, exit, smooth(a / HANDOFF.OUT));
  if (quiet) return a < HANDOFF.ENTER_AT ? mix(exit, REST, smooth((a - HANDOFF.OUT) / (HANDOFF.ENTER_AT - HANDOFF.OUT))) : REST; // no entrance: it simply comes back to rest
  if (a < HANDOFF.ENTER_AT) return mix(exit, pose(t, "start"), smooth((a - HANDOFF.OUT) / (HANDOFF.ENTER_AT - HANDOFF.OUT)));
  if (a < HANDOFF.ENTER_AT + HANDOFF.ENTER) return mix(pose(t, "start"), REST, arrival(t, (a - HANDOFF.ENTER_AT) / HANDOFF.ENTER));
  return REST;
}
/** The body's pose while the exit plays (the aura of the leaving bot lines up with it) and while the entrance plays. */
const leaving = (family, p) => mix(REST, pose(family, "exit"), smooth(p));
const entering = (family, p) => mix(pose(family, "start"), REST, arrival(family, p));

// ---- helpers on primitives ----------------------------------------------------------------------------------------------------------------------
const round = v => Math.round(v * 1000) / 1000;
const faded = (prim, k) => ({ ...prim, opacity: round(clamp(prim.opacity * k)) });
function moved(prim, dx, dy) {
  switch (prim.kind) {
    case "line": return { ...prim, x1: round(prim.x1 + dx), x2: round(prim.x2 + dx), y1: round(prim.y1 + dy), y2: round(prim.y2 + dy) };
    case "arc": case "dot": return { ...prim, cx: round(prim.cx + dx), cy: round(prim.cy + dy) };
    case "rect": return { ...prim, x: round(prim.x + dx), y: round(prim.y + dy) };
    default: return prim;
  }
}
/** Squash across x about `anchor` (the page turning about the body's left edge). */
function squashed(prim, sx, anchor) {
  const at = x => round(anchor + (x - anchor) * sx);
  switch (prim.kind) {
    case "line": return { ...prim, x1: at(prim.x1), x2: at(prim.x2) };
    case "dot": case "arc": return { ...prim, cx: at(prim.cx) };
    case "rect": return { ...prim, x: at(prim.x), w: round(prim.w * sx) };
    default: return prim;
  }
}
const stepped = x => Math.ceil(clamp(x) * 4 - 1e-9) / 4;

// ---- the families ---------------------------------------------------------------------------------------------------------------------------------
/**
 * The aura of the `enter` / `leave` phase, or null when the phase is another one (the caller goes on with its own states).
 * `rest(over)` draws the variant's own resting picture (its idle state, with `over` laid over the input): the fading-in and fading-out parts of
 * every family are that picture, so each variant keeps its own units' shape.
 */
export function handoffAura(family, input, rest) {
  const phase = input?.phase;
  if (!isHandoffPhase(phase)) return null;
  const tier = input?.tier === "M" ? "M" : input?.tier === "L" ? "L" : null;
  if (!tier || input?.reduced) return [];
  const R = num(input?.R, 100), tempo = clamp(num(input?.tempo, 1), 0.5, 2), real = Math.max(0, num(input?.t)) / tempo;
  const resting = () => rest({ phase: "idle", t: real * tempo, settled: null, units: 0, tier });
  const len = phase === "enter" ? ENTER_LEN : LEAVE_LEN;
  if (real >= len) return phase === "enter" ? faded2(resting(), 1) : []; // the exit is over (the body is changing); the entrance has ended in the rest picture
  const p = clamp(real / len), q = smooth(p);
  const out = phase === "enter" ? enterOf(family, p, q, R, real, resting) : leaveOf(family, p, q, R, resting);
  return out;
}
const faded2 = (prims, k) => prims.map(prim => faded(prim, k));

function enterOf(family, p, q, R, real, resting) {
  switch (family) {
    case "dial": {
      // the ring is drawn from a point (0 to 70% of the time) and then goes while the faint ticks it leaves behind come up
      const draw = smooth(p / 0.7), gone = 1 - clamp((p - 0.7) / 0.3), r = 1.28 * R;
      const out = faded2(resting(), smooth((p - 0.5) / 0.5));
      if (draw > 0 && gone > 0) out.push(arc("ring", 0, 0, r, 0, Math.max(0.01, TAU * draw), 2, gone, { w: 0.045 * R }));
      return out;
    }
    case "speed": {
      // the lines stream out behind the body as it slides in, then draw back to the resting length
      const b = entering("speed", p), ext = lerp(1, 0.5, smooth((p - 0.55) / 0.45)), out = [];
      [[0.4, -0.3], [0.8, 0], [0.55, 0.3]].forEach(([length, row], j) => {
        const x1 = (-1.12 + b.dx) * R;
        out.push(line(`flow-${j}`, x1, row * R, x1 - length * ext * R, row * R, 1, lerp(0.9, 0.5, smooth(p)), { w: 0.07 * R, dash: [0.22 * R, 0.14 * R], dashOffset: -real * 1.4 * R }));
      });
      return out;
    }
    case "ticker": {
      // the picture comes in step by step; the two signal arcs flash once when the body lands (the first step of the drop)
      const out = faded2(resting(), stepped(p));
      if (p >= 0.2 && p < 0.45) return out.map(prim => (prim.key.startsWith("arc-") ? { ...prim, tone: 2, opacity: 1 } : prim));
      return out;
    }
    case "halo": {
      const out = [];
      out.push(arc("ring", 0, 0, 1.3 * R * lerp(0.92, 1, q), 0, TAU, 0, lerp(0, 0.5, q), { w: 0.04 * R }));
      return out;
    }
    case "page": {
      // the page turns in about the body's left edge: the lines open out from there
      return faded2(resting(), q).map(prim => squashed(prim, Math.max(0.05, q), -R));
    }
    case "reticle": {
      const r = lerp(1.9, 1.3, q) * R, out = [];
      for (let k = 0; k < 4; k++) out.push(arc(`quarter-${k}`, 0, 0, r, k * (Math.PI / 2) + 0.25, (k + 1) * (Math.PI / 2) - 0.25, 0, lerp(0, 0.5, q), { w: 0.045 * R }));
      return out;
    }
    default: { // dots: the three dots of an orbit gather from outside
      const out = [];
      for (let k = 0; k < 3; k++) { const [x, y] = polar(lerp(2.1, 1.3, q) * R, (k * TAU) / 3); out.push(dot(`dot-${k}`, x, y, 0.06 * R, 0, lerp(0, 0.35, q))); }
      return out;
    }
  }
}

function leaveOf(family, p, q, R, resting) {
  switch (family) {
    case "dial": return [arc("ring", 0, 0, Math.max(0.02 * R, 1.28 * R * (1 - q)), 0, TAU, 2, lerp(0.7, 0.3, q), { w: 0.045 * R })]; // the ring draws in to a point
    case "speed": {
      const b = leaving("speed", p), out = [];
      [[0.4, -0.3], [0.8, 0], [0.55, 0.3]].forEach(([length, row], j) => {
        const x1 = (-1.12 + b.dx) * R;
        out.push(line(`flow-${j}`, x1, row * R, x1 - length * R, row * R, 1, lerp(0.5, 0.9, q) * (1 - 0.4 * q), { w: 0.07 * R, dash: [0.22 * R, 0.14 * R], dashOffset: -p * 0.3 * R }));
      });
      return out; // dashes out to the right, the lines trailing
    }
    case "ticker": return resting().map(prim => faded(moved(prim, 0, -0.6 * R * stepped(p)), 1 - stepped(p))); // lifted away, in steps
    case "halo": return [arc("ring", 0, 0, 1.3 * R, 0, TAU, 0, lerp(0.5, 0, q), { w: 0.04 * R })];
    case "page": return resting().map(prim => faded(squashed(prim, Math.max(0.05, 1 - q), -R), 1 - q)); // turns out about the left edge
    case "reticle": {
      const r = lerp(1.3, 1.9, q) * R, out = [];
      for (let k = 0; k < 4; k++) out.push(arc(`quarter-${k}`, 0, 0, r, k * (Math.PI / 2) + 0.25, (k + 1) * (Math.PI / 2) - 0.25, 0, lerp(0.5, 0, q), { w: 0.045 * R }));
      return out;
    }
    default: {
      const out = [];
      for (let k = 0; k < 3; k++) { const [x, y] = polar(lerp(1.3, 2.1, q) * R, (k * TAU) / 3); out.push(dot(`dot-${k}`, x, y, 0.06 * R, 0, lerp(0.35, 0, q))); }
      return out;
    }
  }
}
