// What the live avatar does each frame with the director's view: the body state, the faces, the gaze, the lean and the nod, the extras.
// Loaded together with BotPresence (not part of the first-screen code); BotBody calls it through `live.drive`.
import type { MutableRefObject } from "react";
import type { BotEngine } from "../../bloub/engine";
import type { StateId } from "../../bloub/states";
import type { DirectorView } from "../../bloub-director.mjs";
import { ENGAGE_TIME, aimFromPointer, easeOutQuint, followLook, pointerFresh, restLook, tourLook } from "../../bloub-gaze.mjs";
import type { LiveHandle } from "./BotBody";
import { VIEW, type AuraFn, type Painter } from "./bot-painter";

const nowSec = () => performance.now() / 1000;
/** Eyes lag a frame behind a freshly set script otherwise (127 px jump in bloub); see BloubBot.vue SCRIPT_MORPH. */
const SCRIPT_MORPH = 1 / 60;
/** How fast a held look is taken up, by the persona's easing. */
const REST_MORPH = { smooth: 0.5, spring: 0.3, step: 0.1 } as const;
/** The nod of a partially finished turn: how far the whole picture drops, as a share of the viewBox. */
const NOD_DEPTH = 0.04;

/** The body's own state, handed over by BotBody each frame (the refs are the body's, the functions set its face layers). */
export interface DriveEnv {
  eng: BotEngine; painter: Painter; svg: SVGSVGElement; clock: number; color: string; size: number; tier: string;
  radii: MutableRefObject<number[] | null>;
  gaze: MutableRefObject<{ aiming: boolean; since: number; rest: null | { yaw: number; pitch: number } }>;
  intro: MutableRefObject<{ on: boolean; since: number }>;
  motion: MutableRefObject<{ tilt: number }>;
  aura: MutableRefObject<AuraFn | undefined>;
  setMood(id: string, morph?: number): void;
  setFace(id: string): void;
}

const CALM = "neutre";

/** Per-frame interaction of the live avatar: the director's pose, then the gaze (arrival turn > the pointer > the pose's own look > released),
 * then the motion of the whole picture (lean, nod) and the extras (amber dot, half-grey, aura). Gaze only drives baseFace states (idle):
 * everywhere else the pose's own gaze IS the animation (orbit, wink...). */
export function drive(env: DriveEnv, h: LiveHandle, view: DirectorView, dt: number) {
  const { eng, painter: p, svg, clock: c } = env, g = env.gaze.current;
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
    const held = view.state === "idle" && !view.follow ? restLook(view.gaze, c) : null;
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
  const draw = env.aura.current;
  if (draw) p.setAura(draw({ t: c, pose: view.pose, units: h.units ?? 0, size: env.size, tier: env.tier, color: env.color }));
}
