// Bot avatar: the bloub engine (src/bloub, vendored, MIT — see THIRD_PARTY_NOTICES.md) rendered as SVG from React.
// The engine is clockless: `sample(t)` is a pure function, so this component only owns a clock and draws what it returns.
// All live avatars share one requestAnimationFrame loop; `frozenAt` draws a single still frame with no loop at all.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { NOTIF_BLUE } from "./bloub/decor";
import { BotEngine, type BotFrame } from "./bloub/engine";
import { DEMI_VIEWBOX, RAYON } from "./bloub/repere";
import { EXPRESSION_BY_ID } from "./bloub/expressions";
import { COLOR_BY_ID, DEFAULT_COLOR, DEFAULT_SHAPE, SHAPE_BY_ID, mixHex } from "./bloub/skins";
import type { StateId } from "./bloub/states";
import type { Director } from "./bloub-director.mjs";
import { ENGAGE_TIME, aimFromPointer, easeOutQuint, followLook, pointerFresh, tourLook } from "./bloub-gaze.mjs";

export type BloubState = StateId;

/** Interaction wiring for the one full-featured avatar: the director picks the state each frame, `pointer` (written by
 * the owner, plain mutable object, no re-render) feeds the gaze. Without it the avatar is the light prop-driven one. */
export interface LiveHandle { director: Director; pointer: { x: number; y: number; at: number } | null }
const nowSec = () => performance.now() / 1000;
/** Eyes lag a frame behind a freshly set script otherwise (127 px jump in bloub); see BloubBot.vue SCRIPT_MORPH. */
const SCRIPT_MORPH = 1 / 60;

type Tick = (dt: number) => void;
const subscribers = new Set<Tick>();
let raf = 0, lastMs = 0;
function loop(ms: number) {
  // Bounded step: a tab that was hidden resumes where it was instead of jumping ahead.
  const dt = lastMs ? Math.min((ms - lastMs) / 1000, 0.064) : 0;
  lastMs = ms;
  for (const tick of subscribers) tick(dt);
  raf = subscribers.size ? requestAnimationFrame(loop) : 0;
  if (!raf) lastMs = 0;
}
function subscribe(tick: Tick) {
  subscribers.add(tick);
  if (!raf) raf = requestAnimationFrame(loop);
  return () => { subscribers.delete(tick); };
}

const reducedMotion = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

// The page's ink for the black "encre" body, so it stays visible in the dark theme.
const PALE = new Set(["creme", "gris"]);
const INK_VAR = "var(--me-ink, #0a0a0c)";

export function BloubAvatar({ state = "idle", size = 40, color = DEFAULT_COLOR, shape = DEFAULT_SHAPE, expression, frozenAt, paper = "#f9f9f9", className, live }: {
  live?: LiveHandle; state?: BloubState; size?: number; color?: string; shape?: string;
  /** Rest expression id (the customiser's face); unset: the engine's own neutral. State animations play on top of it. */
  expression?: string;
  /** Seconds into the state. Set: one still frame, no animation loop (tiny icons, reduced motion). */
  frozenAt?: number; paper?: string; className?: string;
}) {
  const still = frozenAt ?? (reducedMotion() ? 0 : undefined);
  const liveRef = useRef(live); liveRef.current = live;
  const radiiRef = useRef<number[] | null>(null);
  const radii = useMemo(() => SHAPE_BY_ID.get(shape)?.radii ?? null, [shape]);
  radiiRef.current = radii;
  const expr = useMemo(() => (expression ? EXPRESSION_BY_ID.get(expression) ?? null : null), [expression]);
  const hex = COLOR_BY_ID.get(color)?.hex ?? "#0a0a0c";
  const ink = color === "encre" ? INK_VAR : hex;
  const engine = useRef<BotEngine | null>(null);
  if (!engine.current) engine.current = new BotEngine(RAYON, state, radii, expr);
  const clock = useRef(0);
  const [frame, setFrame] = useState<BotFrame>(() => engine.current!.sample(still ?? 0));
  const svgRef = useRef<SVGSVGElement | null>(null);
  const gaze = useRef({ aiming: false, since: 0 });
  const intro = useRef({ on: false, since: 0 });
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const maskId = `bloub-mask-${uid}`;

  // Prop changes go to the engine with the current clock so it morphs instead of jumping.
  useEffect(() => { if (live) return; engine.current!.setState(state, clock.current); if (still !== undefined) setFrame(engine.current!.sample(still)); }, [state, still, live]);
  useEffect(() => { if (liveRef.current && intro.current.on) return; engine.current!.setShape(radii, clock.current); if (still !== undefined) setFrame(engine.current!.sample(still)); }, [radii, still]);
  useEffect(() => { engine.current!.setExpression(expr, clock.current); if (still !== undefined) setFrame(engine.current!.sample(still)); }, [expr, still]);
  useEffect(() => {
    if (still !== undefined) return;
    return subscribe(dt => {
      clock.current += dt;
      if (liveRef.current) drive(liveRef.current);
      setFrame(engine.current!.sample(clock.current));
    });
  }, [still]); // eslint-disable-line react-hooks/exhaustive-deps

  // Per-frame interaction: the director's state, then the gaze (arrival turn > pointer follow > released).
  // Gaze only drives baseFace states (idle): everywhere else the pose's own gaze IS the animation (orbit, wink...).
  function drive(h: LiveHandle) {
    const eng = engine.current!, c = clock.current, view = h.director.read(nowSec());
    if (view.state !== eng.state) eng.setState(view.state as StateId, c);
    const g = gaze.current;
    if (view.intro) {
      if (!intro.current.on) {
        intro.current = { on: true, since: c };
        eng.setShape(null, c); // the arrival turn is only smooth on a circle (bloub docs/intro.md)
        eng.setLook(tourLook(0), c - SCRIPT_MORPH, SCRIPT_MORPH);
      } else eng.setLook(tourLook(c - intro.current.since), c, SCRIPT_MORPH);
      g.aiming = false; return;
    }
    if (intro.current.on) { // landed: back to the bot's own silhouette; release the script (it ends at mix 0 anyway)
      intro.current = { on: false, since: 0 };
      eng.setShape(radiiRef.current, c); eng.setLook(null, c);
    }
    const ptr = h.pointer;
    const box = svgRef.current?.getBoundingClientRect();
    const aim = view.follow && ptr && pointerFresh(ptr.at, nowSec()) ? aimFromPointer(ptr, box, { width: window.innerWidth, height: window.innerHeight }) : null;
    if (aim) {
      if (!g.aiming) { g.aiming = true; g.since = c; }
      eng.setLook(followLook(aim, easeOutQuint((c - g.since) / ENGAGE_TIME)), c);
    } else if (g.aiming) { g.aiming = false; eng.setLook(null, c, ENGAGE_TIME); }
  }

  const view = 120; // crop the viewBox to the body; orbit rings may spill past it (overflow: visible)
  const dot = (d: BotFrame["dots"][number], key: string) => {
    const fill = d.color ?? (d.depth === undefined ? ink : mixHex(paper, hex, d.depth));
    return d.d
      ? <path key={key} d={d.d} style={{ fill }} opacity={d.opacity} transform={`translate(${d.x} ${d.y}) rotate(${d.rot ?? 0}) scale(${RAYON})`} />
      : <circle key={key} cx={d.x} cy={d.y} r={d.r} style={{ fill }} opacity={d.opacity} />;
  };
  return <svg ref={svgRef} className={`bloub-avatar ${className ?? ""}`.trim()} width={size} height={size} viewBox={`${-view} ${-view} ${view * 2} ${view * 2}`} aria-hidden="true" focusable="false" style={{ overflow: "visible" }}>
    <defs>
      <mask id={maskId} maskUnits="userSpaceOnUse" x={-DEMI_VIEWBOX} y={-DEMI_VIEWBOX} width={DEMI_VIEWBOX * 2} height={DEMI_VIEWBOX * 2}>
        <path d={frame.bodyPath} fill="#fff" />
        {frame.eyes.map((eye, i) => <path key={i} d={eye.d} transform={eye.matrix} opacity={eye.alpha} fill="#000" />)}
        {frame.notch && <circle cx={frame.notch.x} cy={frame.notch.y} r={frame.notch.r} fill="#000" />}
      </mask>
      {frame.arcs.map(arc => <linearGradient key={arc.id} id={`${uid}-${arc.id}`} gradientUnits="userSpaceOnUse" x1={arc.grad.x1} y1={arc.grad.y1} x2={arc.grad.x2} y2={arc.grad.y2}>
        {arc.grad.stops.map((c, i) => <stop key={i} offset={i / (arc.grad.stops.length - 1)} stopColor={c} />)}
      </linearGradient>)}
    </defs>
    <g fill="none" strokeLinecap="round">
      {frame.arcs.map(arc => <path key={`b${arc.id}`} d={arc.back} stroke={`url(#${uid}-${arc.id})`} strokeWidth={arc.width} opacity={arc.opacity} />)}
    </g>
    {frame.dotsBehind && <g>{frame.dots.map((d, i) => dot(d, `pb${i}`))}</g>}
    <g opacity={frame.bodyAlpha}>
      {/* Opaque plate under the body so the eye holes do not show the back half of the rings; it takes the page surface. */}
      <path d={frame.bodyPath} style={{ fill: "var(--me-surface, #f9f9f9)" }} />
      <g mask={`url(#${maskId})`}><rect x={-DEMI_VIEWBOX} y={-DEMI_VIEWBOX} width={DEMI_VIEWBOX * 2} height={DEMI_VIEWBOX * 2} style={{ fill: ink }} /></g>
      {/* Cream and light grey would vanish on a light page: a hairline keeps the silhouette readable. */}
      {PALE.has(color) && <path d={frame.bodyPath} fill="none" stroke="var(--me-line-strong, rgba(0,0,0,.28))" strokeWidth={3} vectorEffect="non-scaling-stroke" />}
    </g>
    {!frame.dotsBehind && <g>{frame.dots.map((d, i) => dot(d, `pf${i}`))}</g>}
    {frame.notif && <circle cx={frame.notif.x} cy={frame.notif.y} r={frame.notif.r} fill={NOTIF_BLUE} />}
    <g fill="none" strokeLinecap="round">
      {frame.arcs.map(arc => <path key={`f${arc.id}`} d={arc.front} stroke={`url(#${uid}-${arc.id})`} strokeWidth={arc.width} opacity={arc.opacity} />)}
    </g>
  </svg>;
}
