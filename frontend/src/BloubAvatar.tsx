// Bot avatar: the bloub engine (src/bloub, vendored, MIT — see THIRD_PARTY_NOTICES.md) rendered as SVG from React.
// The engine is clockless: `sample(t)` is a pure function, so this component only owns a clock and draws what it returns.
// All live avatars share one requestAnimationFrame loop; `frozenAt` draws a single still frame with no loop at all.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { NOTIF_BLUE } from "./bloub/decor";
import { BotEngine, type BotFrame } from "./bloub/engine";
import { DEMI_VIEWBOX, RAYON } from "./bloub/repere";
import { COLOR_BY_ID, DEFAULT_COLOR, DEFAULT_SHAPE, SHAPE_BY_ID, mixHex } from "./bloub/skins";
import type { StateId } from "./bloub/states";

export type BloubState = StateId;

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
const INK_VAR = "var(--me-ink, #0a0a0c)";

export function BloubAvatar({ state = "idle", size = 40, color = DEFAULT_COLOR, shape = DEFAULT_SHAPE, frozenAt, paper = "#f9f9f9", className }: {
  state?: BloubState; size?: number; color?: string; shape?: string;
  /** Seconds into the state. Set: one still frame, no animation loop (tiny icons, reduced motion). */
  frozenAt?: number; paper?: string; className?: string;
}) {
  const still = frozenAt ?? (reducedMotion() ? 0 : undefined);
  const radii = useMemo(() => SHAPE_BY_ID.get(shape)?.radii ?? null, [shape]);
  const hex = COLOR_BY_ID.get(color)?.hex ?? "#0a0a0c";
  const ink = color === "encre" ? INK_VAR : hex;
  const engine = useRef<BotEngine | null>(null);
  if (!engine.current) engine.current = new BotEngine(RAYON, state, radii);
  const clock = useRef(0);
  const [frame, setFrame] = useState<BotFrame>(() => engine.current!.sample(still ?? 0));
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const maskId = `bloub-mask-${uid}`;

  // Prop changes go to the engine with the current clock so it morphs instead of jumping.
  useEffect(() => { engine.current!.setState(state, clock.current); if (still !== undefined) setFrame(engine.current!.sample(still)); }, [state, still]);
  useEffect(() => { engine.current!.setShape(radii, clock.current); if (still !== undefined) setFrame(engine.current!.sample(still)); }, [radii, still]);
  useEffect(() => {
    if (still !== undefined) return;
    return subscribe(dt => { clock.current += dt; setFrame(engine.current!.sample(clock.current)); });
  }, [still]);

  const view = 120; // crop the viewBox to the body; orbit rings may spill past it (overflow: visible)
  const dot = (d: BotFrame["dots"][number], key: string) => {
    const fill = d.color ?? (d.depth === undefined ? ink : mixHex(paper, hex, d.depth));
    return d.d
      ? <path key={key} d={d.d} style={{ fill }} opacity={d.opacity} transform={`translate(${d.x} ${d.y}) rotate(${d.rot ?? 0}) scale(${RAYON})`} />
      : <circle key={key} cx={d.x} cy={d.y} r={d.r} style={{ fill }} opacity={d.opacity} />;
  };
  return <svg className={`bloub-avatar ${className ?? ""}`.trim()} width={size} height={size} viewBox={`${-view} ${-view} ${view * 2} ${view * 2}`} aria-hidden="true" focusable="false" style={{ overflow: "visible" }}>
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
    </g>
    {!frame.dotsBehind && <g>{frame.dots.map((d, i) => dot(d, `pf${i}`))}</g>}
    {frame.notif && <circle cx={frame.notif.x} cy={frame.notif.y} r={frame.notif.r} fill={NOTIF_BLUE} />}
    <g fill="none" strokeLinecap="round">
      {frame.arcs.map(arc => <path key={`f${arc.id}`} d={arc.front} stroke={`url(#${uid}-${arc.id})`} strokeWidth={arc.width} opacity={arc.opacity} />)}
    </g>
  </svg>;
}
