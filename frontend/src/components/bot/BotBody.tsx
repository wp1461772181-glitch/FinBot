// The bot's body: the bloub engine (src/bloub, vendored, MIT) drawn into one svg. The engine is clockless (`sample(t)` is a pure
// function), so this component owns a clock and a painter (bot-painter.ts) that writes the frame into existing svg nodes.
// Nothing is rendered by React per frame (design 6.9 P2): M / L avatars write attributes straight onto nodes, an S avatar is a
// still frame plus a CSS breath until something wakes it, an XS avatar is a still frame for good.
//
// Which avatar runs frames: a live one (BotPresence: the director decides the pose each frame) always, except while its director says
// `frozen`; a light one (state / hover driven) only while something moves its picture (bloub-frames.needsFrames). All of them stop
// while off screen or covered by a dialog, and at most one M / L avatar runs at a time (bot-loop.ts).
import { useEffect, useId, useLayoutEffect, useMemo, useRef } from "react";
import { BotEngine } from "../../bloub/engine";
import { liveliness } from "../../bloub/face";
import { RAYON } from "../../bloub/repere";
import { EXPRESSION_BY_ID } from "../../bloub/expressions";
import { COLOR_BY_ID, DEFAULT_COLOR, DEFAULT_SHAPE, SHAPE_BY_ID } from "../../bloub/skins";
import type { StateId } from "../../bloub/states";
import type { Director, DirectorView } from "../../bloub-director.mjs";
import { CALM, MOOD_MORPH, moodAt } from "../../bloub-mood.mjs";
import { rowAim, type RowGazeHandle } from "../../row-gaze.mjs";
import { frameDemand, needsFrames } from "../../bloub-frames.mjs";
import { ENGAGE_TIME, easeOutQuint, followLook, restLook } from "../../bloub-gaze.mjs";
import { FULL_TIERS, tierOf } from "../../bot-sizes.mjs";
import { claimFullLoop, subscribe, type Tick } from "./bot-loop";
import type { DriveEnv } from "./live-drive";
import { VIEW, createPainter, type Painter, type PaintStyle } from "./bot-painter";

export type BloubState = StateId;

/** Interaction wiring for the one full-featured avatar: the director picks the pose each frame, `pointer` (written by the owner, a
 * plain mutable object, no re-render) feeds the gaze, `units` is how many tool calls brought something back (for the aura), and `wake`
 * (set by the body) restarts a stopped loop after an event was sent to the director. */
export interface LiveHandle {
  director: Director; pointer: { x: number; y: number; at: number } | null; units?: number; wake?: () => void;
  /** What happens each frame with the director's view (live-drive.ts, set by BotPresence: it is not part of the first-screen code). */
  drive?: (env: DriveEnv, handle: LiveHandle, view: DirectorView, dt: number) => void;
}

const nowSec = () => performance.now() / 1000;

/** A still frame of a state that moves is taken this many seconds into it (rings formed, the "!" in place, the closed eye drawn); idle is taken as it was. */
const STILL_AFTER: Record<string, number> = { orbit: 1, thinking: 1, wink: 0.6, alert: 2, sleep: 1, notify: 1, exclaim: 1, wide: 1 };
const stillAfter = (state: string) => (state === "idle" ? 0 : STILL_AFTER[state] ?? 1);

let breathSeq = 0;
const reducedMotion = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

// The page's ink for the black "encre" body, so it stays visible in the dark theme.
const PALE = new Set(["creme", "gris"]);
const INK_VAR = "var(--me-ink, #0a0a0c)";

export interface BotBodyProps {
  live?: LiveHandle;
  /** Sidebar rows: set only while the row is hovered; the idle avatar's eyes follow `rowGaze.pointer`. */
  rowGaze?: RowGazeHandle;
  state?: BloubState; size?: number; color?: string; shape?: string;
  /** Seconds into the state. Set: one still frame, no animation loop (tiny icons, reduced motion). */
  frozenAt?: number;
  paper?: string; className?: string;
  /** The aura of a still frame (reduced motion, the sample page): called with the group the aura draws into whenever the frame is painted.
   * A live avatar's aura is drawn per frame by `live.drive` instead. */
  auraStill?: (host: SVGGElement, style: PaintStyle) => void;
  /** The face of a still frame (a work pose in reduced motion); calm when absent. */
  expression?: string;
  /** Still frames: the amber dot of waiting-for-you, and the half-grey of offline. */
  waiting?: boolean; dim?: boolean;
  /** Multiplier on the clock of a light avatar (a live one takes it from its director). */
  tempo?: number;
  /** Still frames: where the eyes look (a gaze kind of bloub-gaze, at time 0) and how far the body leans. */
  gazeKind?: string; tilt?: number;
  /** The sample page only: skip the rule that one M / L avatar runs per screen (it shows five side by side). */
  unlimited?: boolean;
}

export function BotBody({ state = "idle", size = 40, color = DEFAULT_COLOR, shape = DEFAULT_SHAPE, frozenAt, paper = "#f9f9f9", className, live, rowGaze, auraStill, expression, waiting = false, dim = false, tempo = 1, gazeKind, tilt = 0, unlimited = false }: BotBodyProps) {
  const tier = tierOf(size);
  const full = FULL_TIERS.includes(tier) && !unlimited;
  const still = frozenAt ?? (tier === "XS" || reducedMotion() ? 0 : undefined);
  const liveRef = useRef(live); liveRef.current = live;
  const rowGazeRef = useRef(rowGaze); rowGazeRef.current = rowGaze;
  const stateRef = useRef(state); stateRef.current = state;
  const tempoRef = useRef(tempo); tempoRef.current = tempo;
  const auraStillRef = useRef(auraStill); auraStillRef.current = auraStill;
  const radii = useMemo(() => SHAPE_BY_ID.get(shape)?.radii ?? null, [shape]);
  const radiiRef = useRef<number[] | null>(null); radiiRef.current = radii;
  const hex = COLOR_BY_ID.get(color)?.hex ?? "#0a0a0c";
  const style: PaintStyle = { hex, ink: color === "encre" ? INK_VAR : hex, pale: PALE.has(color), paper };
  const styleRef = useRef(style); styleRef.current = style;
  const sizeRef = useRef({ size, tier }); sizeRef.current = { size, tier };
  // Every bot rests on the same calm face; work poses lay a face over the body (see setMood / setFace).
  const restExpression = EXPRESSION_BY_ID.get(expression ?? CALM) ?? EXPRESSION_BY_ID.get(CALM) ?? null;
  const engine = useRef<BotEngine | null>(null);
  if (!engine.current) engine.current = new BotEngine(RAYON, state, radii, restExpression);
  const clock = useRef(0);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const painter = useRef<Painter | null>(null);
  const gaze = useRef({ aiming: false, since: 0, rest: null as null | { yaw: number; pitch: number } });
  const face = useRef({ mood: CALM, moodSince: 0, wasOrbit: false, rest: expression ?? CALM });
  const motion = useRef({ tilt: 0 });
  const intro = useRef({ on: false, since: 0 });
  const loop = useRef<{ wake: () => void } | null>(null);
  const quietSince = useRef(-Infinity);
  const running = useRef(false);
  const parked = useRef(!live && still === undefined && !needsFrames({ state, hovered: Boolean(rowGaze) }));
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  // Resting avatars breathe out of step with each other: a fixed negative delay per instance (golden-ratio spacing), within the 4 s period of `.bot-breathe`.
  const breathDelay = useMemo(() => `-${((breathSeq++ * 1.618) % 4).toFixed(2)}s`, []);

  const paintNow = () => {
    const eng = engine.current!;
    painter.current?.paint(eng.sample(still !== undefined ? still + stillAfter(stateRef.current) : clock.current), styleRef.current);
    if (painter.current) auraStillRef.current?.(painter.current.auraHost, styleRef.current);
  };
  const markParked = (on: boolean) => {
    parked.current = on;
    svgRef.current?.classList.toggle("bot-breathe", on && tier !== "XS");
  };

  useLayoutEffect(() => {
    const svg = svgRef.current!;
    painter.current = createPainter(svg, uid);
    svg.style.animationDelay = breathDelay;
    svg.classList.toggle("bot-breathe", parked.current && tier !== "XS");
    svg.setAttribute("data-tier", tier);
    paintNow();
    return () => { painter.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // React may rewrite className when its prop changes: put the breath back.
  useLayoutEffect(() => { svgRef.current?.classList.toggle("bot-breathe", parked.current && tier !== "XS"); });
  useLayoutEffect(() => { svgRef.current?.setAttribute("data-tier", tier); }, [tier]);

  // Static extras follow their props (a live avatar sets these per frame instead).
  useLayoutEffect(() => { if (liveRef.current) return; painter.current?.setWaiting(waiting); painter.current?.place(tilt, 0); }, [waiting, live, tilt]);
  // A still frame's aura follows the owner (it changes with every state the owner shows).
  useLayoutEffect(() => { if (painter.current && auraStill) auraStill(painter.current.auraHost, styleRef.current); });

  // Prop changes go to the engine with the current clock so it morphs instead of jumping.
  useEffect(() => {
    if (live) return;
    engine.current!.setState(state, still ?? clock.current);
    if (still !== undefined) {
      // A still frame of a work pose wears its face at once (time -10: the morph is long over at `still`).
      engine.current!.setExpression(restExpression, still - 10);
      engine.current!.setMood(state === "orbit" && expression && expression !== CALM ? EXPRESSION_BY_ID.get(expression) ?? null : null, still - 10, MOOD_MORPH);
      engine.current!.setLook(state === "idle" && gazeKind ? restLook(gazeKind, 0) : null, still - 10, 0.01);
      paintNow();
    }
  }, [state, still, live, expression, gazeKind]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (liveRef.current && intro.current.on) return; engine.current!.setShape(radii, clock.current); if (still !== undefined) paintNow(); }, [radii, still]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!running.current) paintNow(); }, [hex, color, paper]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (still !== undefined) return;
    const svg = svgRef.current!;
    let off: (() => void) | null = null, release: (() => void) | null = null;
    let wanting = false, granted = !full, visible = true, covered = false, coverTimer = 0, frames = 0;

    const sync = () => {
      const should = wanting && granted && visible && !covered;
      if (should && !off) off = subscribe(tick);
      else if (!should && off) { off(); off = null; if (wanting && !granted) paintNow(); }
      running.current = Boolean(off);
    };
    const setWant = (on: boolean) => {
      if (on === wanting) return;
      wanting = on;
      if (full) {
        if (on) release = claimFullLoop(sizeRef.current.size, `${tier} avatar`, g => { granted = g; sync(); });
        else { release?.(); release = null; granted = false; }
      }
      sync();
    };
    const isCovered = () => Boolean(svg.closest('[data-slot="bot-avatar"]')?.parentElement?.closest('[inert], [data-aria-hidden="true"]'));
    const watchCover = () => {
      if (coverTimer || !isCovered()) return;
      covered = true; sync();
      coverTimer = window.setInterval(() => { if (isCovered()) return; window.clearInterval(coverTimer); coverTimer = 0; covered = false; sync(); }, 500);
    };

    const tick: Tick = dt => {
      const h = liveRef.current;
      if (++frames % 30 === 0) { watchCover(); if (covered) return; }
      if (h) {
        const view = h.director.read(nowSec());
        clock.current += dt * view.tempo;
        h.drive?.({ eng: engine.current!, painter: painter.current!, svg, clock: clock.current, style: styleRef.current, size: sizeRef.current.size, tier: sizeRef.current.tier, radii: radiiRef, gaze, intro, motion, setMood, setFace }, h, view, dt);
        painter.current?.paint(engine.current!.sample(clock.current), styleRef.current);
        if (view.frozen) setWant(false); // this frame is the still one: stop until the owner sends something
        return;
      }
      clock.current += dt * tempoRef.current;
      rowMood(); if (rowGazeRef.current || gaze.current.aiming) steerRow(rowGazeRef.current?.pointer ?? null); // nothing else runs for a row nobody hovers
      painter.current?.paint(engine.current!.sample(clock.current), styleRef.current);
      // Back to a still frame once nothing moves the picture and the engine has settled (eyes open: never rest mid-blink).
      const input = { state: stateRef.current, hovered: Boolean(rowGazeRef.current), aiming: gaze.current.aiming };
      if (frameDemand(input)) quietSince.current = clock.current;
      else if (!needsFrames({ ...input, quietFor: clock.current - quietSince.current }) && liveliness(clock.current, { wander: 0, float: false }).lid >= 1) { setWant(false); markParked(true); }
    };

    const wake = () => { markParked(false); setWant(true); };
    loop.current = { wake };
    if (liveRef.current) liveRef.current.wake = wake;
    const watcher = typeof IntersectionObserver === "function" ? new IntersectionObserver(entries => { visible = entries[entries.length - 1]!.isIntersecting; sync(); }) : null;
    watcher?.observe(svg);
    if (liveRef.current || needsFrames({ state: stateRef.current, hovered: Boolean(rowGazeRef.current) })) wake();
    return () => {
      off?.(); off = null; release?.(); release = null; watcher?.disconnect(); window.clearInterval(coverTimer);
      loop.current = null; if (liveRef.current?.wake === wake) liveRef.current.wake = undefined;
    };
  }, [Boolean(live), still]); // eslint-disable-line react-hooks/exhaustive-deps
  // Something changed that a resting avatar must animate (a state, a hover, a new silhouette): get frames for a while.
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    quietSince.current = clock.current;
    loop.current?.wake();
  }, [state, Boolean(rowGaze), radii]);

  // The work face over the orbit body: same sequence as the main avatar's (bloub-mood). A row only knows "running", so it plays the waiting sequence.
  function setMood(id: string, morph = MOOD_MORPH) {
    const f = face.current;
    if (f.mood === id) return;
    f.mood = id;
    engine.current!.setMood(id === CALM ? null : EXPRESSION_BY_ID.get(id) ?? null, clock.current, morph);
  }
  // The resting face on the idle base (listening, a tool running, verifying, waiting for you wear one; the engine ignores it on other bodies).
  function setFace(id: string) {
    const f = face.current;
    if (f.rest === id) return;
    f.rest = id;
    engine.current!.setExpression(EXPRESSION_BY_ID.get(id) ?? EXPRESSION_BY_ID.get(CALM) ?? null, clock.current);
  }
  function rowMood() {
    const f = face.current, orbit = stateRef.current === "orbit";
    if (orbit && !f.wasOrbit) f.moodSince = clock.current;
    f.wasOrbit = orbit;
    setMood(orbit ? moodAt("waiting", clock.current - f.moodSince) : CALM);
  }

  // Sidebar row: follow the hovered pointer on the idle base only; once the hover ends (or a state takes over) release it.
  function steerRow(ptr: RowGazeHandle["pointer"]) {
    const eng = engine.current!, c = clock.current, g = gaze.current;
    const box = svgRef.current?.getBoundingClientRect();
    const aim = rowAim(ptr, stateRef.current, nowSec(), box, { width: window.innerWidth, height: window.innerHeight });
    if (aim) {
      if (!g.aiming) { g.aiming = true; g.since = c; }
      eng.setLook(followLook(aim, easeOutQuint((c - g.since) / ENGAGE_TIME)), c);
    } else if (g.aiming) { g.aiming = false; eng.setLook(null, c, ENGAGE_TIME); }
  }

  return <svg ref={svgRef} data-slot="bot-body" className={`bloub-avatar ${className ?? ""}`.trim()} width={size} height={size}
    viewBox={`${-VIEW} ${-VIEW} ${VIEW * 2} ${VIEW * 2}`} aria-hidden="true" focusable="false" style={{ overflow: "visible" }}
    {...(live ? {} : { "data-dim": dim ? "true" : undefined })} />;
}
