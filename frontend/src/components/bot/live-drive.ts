// What the live avatar does each frame with the director's view: the body state, the faces, the gaze, the lean and the nod, the extras.
// Loaded together with BotPresence (not part of the first-screen code); BotBody calls it through `live.drive`.
import type { MutableRefObject } from "react";
import type { BotEngine } from "../../bloub/engine";
import type { StateId } from "../../bloub/states";
import type { DirectorView } from "../../bloub-director.mjs";
import { ENGAGE_TIME, aimFromPointer, easeOutQuint, followLook, pointerFresh, restLook, tourLook } from "../../bloub-gaze.mjs";
import { RAYON } from "../../bloub/repere";
import { auraFor } from "../../aura/index.mjs";
import { sweepAngle, sweepLook } from "../../aura/gaze.mjs";
import { bodyMotion } from "../../aura/motion.mjs";
import { createTracker, type Tracker } from "../../aura/track.mjs";
import { handoffBody } from "../../aura/handoff.mjs";
import { HANDOFF } from "../../handoff.mjs";
import { COLOR_BY_ID, SHAPE_BY_ID, mixHex } from "../../bloub/skins";
import type { LiveHandle, WornLook } from "./BotBody";
import { clearAura, drawAura } from "./aura-paint";
import { VIEW, type Painter, type PaintStyle } from "./bot-painter";

const nowSec = () => performance.now() / 1000;
/** Eyes lag a frame behind a freshly set script otherwise (127 px jump in bloub); see BloubBot.vue SCRIPT_MORPH. */
const SCRIPT_MORPH = 1 / 60;
/** How fast a held look is taken up, by the persona's easing. */
const REST_MORPH = { smooth: 0.5, spring: 0.3, step: 0.1 } as const;
/** The nod of a partially finished turn: how far the whole picture drops, as a share of the viewBox. */
const NOD_DEPTH = 0.04;

/** The body's own state, handed over by BotBody each frame (the refs are the body's, the functions set its face layers). */
export interface DriveEnv {
  eng: BotEngine; painter: Painter; svg: SVGSVGElement; clock: number; style: PaintStyle; size: number; tier: string;
  radii: MutableRefObject<number[] | null>;
  gaze: MutableRefObject<{ aiming: boolean; since: number; rest: null | { yaw: number; pitch: number } }>;
  intro: MutableRefObject<{ on: boolean; since: number }>;
  motion: MutableRefObject<{ tilt: number }>;
  setMood(id: string, morph?: number): void;
  setFace(id: string): void;
}

const CALM = "neutre";
/** One aura tracker per live avatar (it remembers when the state began and when each unit came back). */
const trackers = new WeakMap<LiveHandle, Tracker>();

/** What an avatar remembers between frames about its change of look: the silhouette being morphed (so a redirect starts from where the picture is,
 * the engine's own morph would start from the target it was heading for), the colour being mixed, the aura variant that is drawn. */
interface Wardrobe { morph: { from: number[] | null; to: number[] | null; at: number } | null; tween: Tween | null; shown: string | null; aura: string | null }
interface Tween { from: string; to: string; toInk: string; fromPale: boolean; toPale: boolean; at: number }
const wardrobes = new WeakMap<LiveHandle, Wardrobe>();
const PALE = new Set(["creme", "gris"]);
const INK_VAR = "var(--me-ink, #0a0a0c)";
const SHAPE_MORPH = 0.45; // BotEngine.SHAPE_MORPH
const hexOf = (color: string) => COLOR_BY_ID.get(color)?.hex ?? "#0a0a0c";
const radiiOf = (shape: string) => SHAPE_BY_ID.get(shape)?.radii ?? null;

/** Put on the wanted look: the silhouette goes to the engine (from the shape the picture is showing), the colour starts its 240 ms mix. */
function wear(env: DriveEnv, h: LiveHandle, wardrobe: Wardrobe, c: number) {
  const look = h.look!, from: WornLook = look.worn, to: WornLook = look.want;
  if (to.shape !== from.shape) {
    const m = wardrobe.morph, next = radiiOf(to.shape);
    let start = radiiOf(from.shape);
    // a redirect in the middle of a morph: the engine would start again from the shape it was heading for, so give it the one on screen first
    if (m?.from && m.to && c - m.at < SHAPE_MORPH) {
      const k = easeOutQuint((c - m.at) / SHAPE_MORPH);
      start = m.from.map((r, i) => r + ((m.to![i] ?? r) - r) * k);
      env.eng.setShape(start, c);
    }
    if (!env.intro.current.on) env.eng.setShape(next, c); // during the arrival turn the circle is imposed; BotBody puts the silhouette back when it lands
    wardrobe.morph = { from: start, to: next, at: c };
  }
  if (to.color !== from.color) {
    wardrobe.tween = { from: wardrobe.shown ?? hexOf(from.color), to: hexOf(to.color), toInk: to.color === "encre" ? INK_VAR : hexOf(to.color), fromPale: PALE.has(from.color), toPale: PALE.has(to.color), at: nowSec() };
  }
  look.worn = to;
  look.onWear?.(to);
}

/** The colour of the body this frame: the mix while a change of colour is under way (design 6.7: 240 ms), written into the style the painter reads. */
function tint(env: DriveEnv, wardrobe: Wardrobe) {
  const tw = wardrobe.tween;
  if (!tw) return;
  const k = Math.min(1, (nowSec() - tw.at) / HANDOFF.COLOR);
  if (k >= 1) { env.style.hex = tw.to; env.style.ink = tw.toInk; env.style.pale = tw.toPale; wardrobe.shown = tw.to; wardrobe.tween = null; return; }
  const mixed = mixHex(tw.from, tw.to, k);
  env.style.hex = mixed; env.style.ink = mixed; env.style.pale = k < 0.5 ? tw.fromPale : tw.toPale; wardrobe.shown = mixed;
}

/** Per-frame interaction of the live avatar: the director's pose, then the gaze (arrival turn > the pointer > the pose's own look > released),
 * then the motion of the whole picture (lean, nod) and the extras (amber dot, half-grey, aura and the body's own aura motions). Gaze only drives baseFace states (idle):
 * everywhere else the pose's own gaze IS the animation (orbit, wink...). */
export function drive(env: DriveEnv, h: LiveHandle, view: DirectorView, dt: number) {
  const { eng, painter: p, svg, clock: c } = env, g = env.gaze.current;
  // The aura first: its state decides where the eyes go while a tool runs (the moving point of a dial, a halo, a scan).
  const full = env.tier === "M" || env.tier === "L";
  let tracker = trackers.get(h);
  if (!tracker) trackers.set(h, tracker = createTracker());
  const input = tracker.step({ clock: c, now: nowSec(), view, units: h.units ?? 0 });
  let wardrobe = wardrobes.get(h);
  if (!wardrobe) wardrobes.set(h, wardrobe = { morph: null, tween: null, shown: null, aura: null });
  // The new look goes on when the director's persona has swapped (the exit of the old aura is over), not at the click.
  const look = h.look;
  if (look && view.handoff?.phase !== "leave" && (look.want.shape !== look.worn.shape || look.want.color !== look.worn.color)) wear(env, h, wardrobe, c);
  tint(env, wardrobe);
  if (view.state !== eng.state) eng.setState(view.state as StateId, c);
  env.setMood(view.state === "orbit" ? view.expression : CALM, view.moodMorph);
  env.setFace(view.state === "idle" ? view.expression : CALM);
  if (view.intro) {
    if (!env.intro.current.on) {
      env.intro.current = { on: true, since: c };
      eng.setShape(null, c); // the arrival turn is only smooth on a circle (bloub docs/intro.md)
      eng.setLook(tourLook(0), c - SCRIPT_MORPH, SCRIPT_MORPH);
    } else eng.setLook(tourLook(c - env.intro.current.since), c, SCRIPT_MORPH);
    g.aiming = false; g.rest = null;
  } else {
    if (env.intro.current.on) { // landed: back to the bot's own silhouette; release the script (it ends at mix 0 anyway)
      env.intro.current = { on: false, since: 0 };
      eng.setShape(env.radii.current, c); eng.setLook(null, c);
    }
    const ptr = h.pointer;
    const aim = view.follow && ptr && pointerFresh(ptr.at, nowSec()) ? aimFromPointer(ptr, svg.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }) : null;
    const held = view.state === "idle" && !view.follow ? (view.gaze === "sweep" && view.pose === "tool" ? sweepLook(sweepAngle(view.aura, input.t, input.turn)) : restLook(view.gaze, c)) : null;
    if (aim) {
      g.rest = null;
      if (!g.aiming) { g.aiming = true; g.since = c; }
      eng.setLook(followLook(aim, easeOutQuint((c - g.since) / ENGAGE_TIME)), c);
    } else if (held) {
      // A look the persona or the pose asks for (scan, glance, side, below...): set it when it changes, the engine glides there.
      g.aiming = false;
      if (!g.rest || g.rest.yaw !== held.yaw || g.rest.pitch !== held.pitch) { g.rest = { yaw: held.yaw, pitch: held.pitch }; eng.setLook(held, c, REST_MORPH[view.easing] ?? REST_MORPH.smooth); }
    } else if (g.aiming || g.rest) { g.aiming = false; g.rest = null; eng.setLook(null, c, ENGAGE_TIME); }
  }
  // The whole picture: the tracker's forward lean follows the pose smoothly; the partial nod drops 4% and returns.
  const m = env.motion.current;
  m.tilt += (view.tilt - m.tilt) * Math.min(1, dt * 6);
  p.place(Math.abs(m.tilt) < 0.01 ? 0 : m.tilt, view.nod === null ? 0 : Math.sin(Math.PI * view.nod) * NOD_DEPTH * VIEW * 2);
  p.setWaiting(view.waitingForUser);
  svg.setAttribute("data-dim", view.dim ? "true" : "false");
  // What the checks read (no secrets): the engine clock, the director's pose and state, the gaze, the tempo.
  svg.setAttribute("data-clock", c.toFixed(3)); svg.setAttribute("data-pose", view.pose); svg.setAttribute("data-state", view.state);
  svg.setAttribute("data-gaze", view.gaze); svg.setAttribute("data-tempo", String(view.tempo));
  svg.setAttribute("data-handoff", view.handoff?.phase ?? "");
  if (full) {
    // another aura takes the place of this one (a handoff, a late persona): nothing of the old one stays on the page, not even hidden
    if (wardrobe.aura !== view.aura) { if (wardrobe.aura !== null) clearAura(p.auraHost); wardrobe.aura = view.aura; p.auraHost.setAttribute("data-aura-variant", view.aura); }
    drawAura(p.auraHost, auraFor(view.aura)({ ...input, R: RAYON, tier: env.tier }), env.style, input.phase);
    const hand = view.handoff;
    if (hand) { // a handoff: the old body half leaves, the new one arrives (design 6.5, 6.7): the pose is one continuous curve over the whole time
      const b = handoffBody({ from: hand.from, to: hand.to, age: hand.age, quiet: hand.quiet, carry: hand.carry });
      p.move(b.dx * RAYON, b.tilt, b.scale, b.dy * RAYON, b.sx, b.alpha);
    } else {
      // the body's own movements that belong to the aura (TeslaBot's dart / brake / lean, AppleBot's settle): a transform, the engine is not touched
      const body = bodyMotion({ variant: view.aura, phase: input.phase, real: input.t / view.tempo, ages: input.ages });
      p.move(body.dx * RAYON, body.tilt, body.scale);
    }
  }
}
