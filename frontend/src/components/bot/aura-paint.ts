// Draws an aura's primitives (src/aura: plain data) into the avatar's aura group, reusing one svg node per primitive `key` so units that come and
// go never shift the others.  Loaded with the live avatar (it is not part of the first-screen code): the painter only owns the empty group.
import { TONE_LEVELS } from "../../aura/tones.mjs";
import type { AuraPrim } from "../../aura/shared.mjs";
import type { PaintStyle } from "./bot-painter";

const NS = "http://www.w3.org/2000/svg";
const TAG = { line: "line", arc: "path", dot: "circle", rect: "rect", path: "path" } as const;
const INK = "var(--me-ink, #0a0a0c)", AMBER = "var(--action, #9a4a06)", DANGER = "var(--danger, #c4281c)";

type Cached = { _a?: Record<string, string> };
function put(node: Element, name: string, value: string | number | null) {
  const text = value === null ? "" : String(value), cache = ((node as unknown as Cached)._a ??= {});
  if (cache[name] === text) return;
  cache[name] = text;
  if (value === null) node.removeAttribute(name); else node.setAttribute(name, text);
}
function style(node: SVGElement, prop: string, value: string) {
  const cache = ((node as unknown as Cached)._a ??= {}), key = `s:${prop}`;
  if (cache[key] !== value) { cache[key] = value; node.style.setProperty(prop, value); }
}

interface Entry { el: SVGElement; tag: string; frame: number }
const hosts = new WeakMap<SVGGElement, { nodes: Map<string, Entry>; frame: number }>();

const point = (cx: number, cy: number, r: number, a: number) => `${(cx + r * Math.sin(a)).toFixed(2)} ${(cy - r * Math.cos(a)).toFixed(2)}`;
/** The path of an arc (angles clockwise from the top).  A whole circle is two half arcs: one arc cannot end where it starts. */
export function arcPath(cx: number, cy: number, r: number, a0: number, a1: number) {
  const span = a1 - a0, from = point(cx, cy, r, a0);
  if (span >= Math.PI * 2 - 1e-3) return `M ${from} A ${r} ${r} 0 1 1 ${point(cx, cy, r, a0 + Math.PI)} A ${r} ${r} 0 1 1 ${from}`;
  return `M ${from} A ${r} ${r} 0 ${span > Math.PI ? 1 : 0} 1 ${point(cx, cy, r, a1)}`;
}

/** The colour of a primitive: the bot's own (tone 0, 1, 2 differ in opacity only), the page ink, or one of the two semantic colours. */
const colorOf = (tone: AuraPrim["tone"], ink: string) => (typeof tone === "number" ? ink : tone === "ink" ? INK : tone === "amber" ? AMBER : DANGER);

/**
 * Show `prims` in `host`.  What the checks read is written on the group: data-aura-phase, data-aura-units (nodes of units that came back),
 * data-aura-form (closed / gap / broken / none) and data-aura-nodes (nodes showing), and on each unit's node data-aura-unit.
 */
export function drawAura(host: SVGGElement, prims: ReadonlyArray<AuraPrim>, paint: Pick<PaintStyle, "ink">, phase: string) {
  let state = hosts.get(host);
  if (!state) { state = { nodes: new Map(), frame: 0 }; hosts.set(host, state); }
  const frame = ++state.frame;
  let unitCount = 0, form = "none";
  for (const prim of prims) {
    const tag = TAG[prim.kind];
    let entry = state.nodes.get(prim.key);
    if (entry && entry.tag !== tag) { entry.el.remove(); state.nodes.delete(prim.key); entry = undefined; }
    if (!entry) {
      const el = document.createElementNS(NS, tag) as SVGElement;
      el.setAttribute("data-aura-key", prim.key);
      host.appendChild(el);
      entry = { el, tag, frame };
      state.nodes.set(prim.key, entry);
    }
    entry.frame = frame;
    const el = entry.el, color = colorOf(prim.tone, paint.ink), filled = prim.kind === "dot" || prim.kind === "rect";
    put(el, "display", null);
    switch (prim.kind) {
      case "line": put(el, "x1", prim.x1); put(el, "y1", prim.y1); put(el, "x2", prim.x2); put(el, "y2", prim.y2); break;
      case "arc": put(el, "d", arcPath(prim.cx, prim.cy, prim.r, prim.a0, prim.a1)); break;
      case "dot": put(el, "cx", prim.cx); put(el, "cy", prim.cy); put(el, "r", prim.r); break;
      case "rect": put(el, "x", prim.x - prim.w / 2); put(el, "y", prim.y - prim.h / 2); put(el, "width", prim.w); put(el, "height", prim.h); put(el, "rx", prim.w * 0.2); break;
      case "path": put(el, "d", prim.d); break;
    }
    style(el, "fill", filled ? color : "none");
    style(el, "stroke", filled ? "none" : color);
    if (!filled) { put(el, "stroke-width", prim.w ?? 4); put(el, "stroke-linecap", "round"); put(el, "stroke-linejoin", "round"); }
    put(el, "stroke-dasharray", prim.dash ? `${prim.dash[0]} ${prim.dash[1]}` : null);
    put(el, "stroke-dashoffset", prim.dashOffset ?? null);
    put(el, "opacity", (prim.opacity * (typeof prim.tone === "number" ? TONE_LEVELS[prim.tone]! : 1)).toFixed(3));
    put(el, "class", prim.anim === "slow-blink" ? "aura-slow-blink" : null);
    put(el, "data-aura-unit", prim.unit ?? null);
    if (prim.unit !== undefined) unitCount++;
    if (prim.form) form = prim.form;
  }
  for (const entry of state.nodes.values()) if (entry.frame !== frame) put(entry.el, "display", "none");
  put(host, "data-aura-phase", phase);
  put(host, "data-aura-units", unitCount);
  put(host, "data-aura-form", form);
  put(host, "data-aura-nodes", prims.length);
}
