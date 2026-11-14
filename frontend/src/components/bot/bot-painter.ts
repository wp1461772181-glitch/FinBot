// Imperative SVG painter for the bloub engine frames (design 6.9 P2): the svg is built once and every frame only sets attributes on the
// nodes that already exist. React never re-renders per frame.
import type { BotFrame } from "../../bloub/engine";
import { NOTIF_BLUE } from "../../bloub/decor";
import { DEMI_VIEWBOX, RAYON } from "../../bloub/repere";
import { mixHex } from "../../bloub/skins";

const NS = "http://www.w3.org/2000/svg";
/** Half the visible viewBox: the body is cropped to it, rings may spill past it. */
export const VIEW = 120;

/** What the aura slot gets (A2 fills it): time on the avatar's clock, the pose, how many tool calls brought something back, the size. */
export interface AuraContext { t: number; pose: string; units: number; size: number; tier: string; color: string }
/** One shape of an aura. `tag` is any svg shape; `attrs` are set as given. */
export interface AuraPrimitive { tag: "circle" | "path" | "line" | "rect" | "ellipse"; attrs: Record<string, string | number> }
export type AuraFn = (ctx: AuraContext) => ReadonlyArray<AuraPrimitive> | null | undefined;

/** The three opacity steps the thinking rings take on the bot's own colour (start, middle, end of each ring's gradient). */
export const RING_LEVELS = [0.34, 0.66, 1] as const;

export interface PaintStyle {
  /** The colour's own hex (skins.ts). */
  hex: string;
  /** What the body and the rings are filled with: the page ink for "encre" (so it shows in dark), else the hex. */
  ink: string;
  /** Cream and light grey bodies get a hairline so they show on a light page. */
  pale: boolean;
  paper: string;
}

type Cached = { _c?: Record<string, string> };
function put(node: Element, name: string, value: string | number) {
  const text = String(value), cache = ((node as unknown as Cached)._c ??= {});
  if (cache[name] !== text) { cache[name] = text; node.setAttribute(name, text); }
}
function putStyle(node: SVGElement, prop: string, value: string) {
  const cache = ((node as unknown as Cached)._c ??= {}), key = `s:${prop}`;
  if (cache[key] !== value) { cache[key] = value; node.style.setProperty(prop, value); }
}
function make<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}): SVGElementTagNameMap[K] {
  const node = document.createElementNS(NS, tag);
  for (const [name, value] of Object.entries(attrs)) put(node, name, value);
  return node;
}
const show = (node: Element, on: boolean) => put(node, "display", on ? "inline" : "none");

/** A list of same-purpose nodes that grows when a frame needs more and only hides the extras. */
class Pool {
  private nodes: SVGElement[] = [];
  private tags: string[] = [];
  constructor(private host: SVGElement) {}
  at(i: number, tag: string): SVGElement {
    if (this.nodes[i] && this.tags[i] !== tag) { this.nodes[i]!.remove(); delete this.nodes[i]; }
    if (!this.nodes[i]) {
      const node = document.createElementNS(NS, tag) as SVGElement;
      this.nodes[i] = node; this.tags[i] = tag;
      this.host.appendChild(node);
    }
    show(this.nodes[i]!, true);
    return this.nodes[i]!;
  }
  trim(count: number) { for (let i = count; i < this.nodes.length; i++) if (this.nodes[i]) show(this.nodes[i]!, false); }
}

export interface Painter {
  paint(frame: BotFrame, style: PaintStyle): void;
  /** The amber dot of "waiting for you". Constant: never blinks. */
  setWaiting(on: boolean): void;
  setAura(prims: ReadonlyArray<AuraPrimitive> | null | undefined): void;
  /** Whole-picture placement: lean in degrees and a vertical offset in viewBox units. */
  place(tilt: number, dy: number): void;
}

export function createPainter(svg: SVGSVGElement, uid: string): Painter {
  const maskId = `bloub-mask-${uid}`;
  const defs = make("defs");
  const mask = make("mask", { id: maskId, maskUnits: "userSpaceOnUse", x: -DEMI_VIEWBOX, y: -DEMI_VIEWBOX, width: DEMI_VIEWBOX * 2, height: DEMI_VIEWBOX * 2 });
  const maskBody = make("path", { fill: "#fff" });
  const maskEyes = make("g");
  const maskNotch = make("circle", { fill: "#000" });
  mask.append(maskBody, maskEyes, maskNotch);
  const gradients = make("g");
  defs.append(mask, gradients);

  const root = make("g", { "data-slot": "bot-motion" });
  const arcsBack = make("g", { fill: "none", "stroke-linecap": "round" });
  const dotsBehind = make("g");
  const bodyGroup = make("g");
  const plate = make("path");
  plate.style.fill = "var(--me-surface, #f9f9f9)"; // opaque plate: the eye holes must not show the back half of the rings
  const masked = make("g", { mask: `url(#${maskId})` });
  const fill = make("rect", { x: -DEMI_VIEWBOX, y: -DEMI_VIEWBOX, width: DEMI_VIEWBOX * 2, height: DEMI_VIEWBOX * 2 });
  masked.appendChild(fill);
  const rim = make("path", { fill: "none", "stroke-width": 3, "vector-effect": "non-scaling-stroke" });
  rim.style.stroke = "var(--me-line-strong, rgba(0,0,0,.28))";
  bodyGroup.append(plate, masked, rim);
  const dotsFront = make("g");
  const notif = make("circle", { fill: NOTIF_BLUE });
  const arcsFront = make("g", { fill: "none", "stroke-linecap": "round" });
  const auraGroup = make("g", { "data-slot": "bot-aura" });
  // The amber dot sits low on the right, the way the unread dot sits high on the right; a surface-coloured ring separates it from the body.
  const waitingRing = make("circle", { cx: RAYON * 0.72, cy: RAYON * 0.72, r: RAYON * 0.23, display: "none", "data-slot": "waiting-ring" });
  waitingRing.style.fill = "var(--me-surface, #f9f9f9)";
  const waitingDot = make("circle", { cx: RAYON * 0.72, cy: RAYON * 0.72, r: RAYON * 0.17, display: "none", "data-slot": "waiting-dot" });
  waitingDot.style.fill = "var(--action, #9a4a06)";
  root.append(arcsBack, dotsBehind, bodyGroup, dotsFront, notif, arcsFront, auraGroup, waitingRing, waitingDot);
  svg.replaceChildren(defs, root);

  const eyePool = new Pool(maskEyes);
  const behindPool = new Pool(dotsBehind), frontPool = new Pool(dotsFront);
  const backArcs = new Pool(arcsBack), frontArcs = new Pool(arcsFront);
  const auraPool = new Pool(auraGroup);
  const gradientNodes: { grad: SVGLinearGradientElement; stops: SVGStopElement[] }[] = [];
  const gradient = (i: number) => {
    if (!gradientNodes[i]) {
      const grad = make("linearGradient", { id: `${uid}-g${i}`, gradientUnits: "userSpaceOnUse" });
      const stops = [0, 1, 2].map(k => make("stop", { offset: k / 2 }));
      grad.append(...stops); gradients.appendChild(grad);
      gradientNodes[i] = { grad, stops };
    }
    return gradientNodes[i]!;
  };

  return {
    paint(frame, style) {
      put(maskBody, "d", frame.bodyPath);
      frame.eyes.forEach((eye, i) => {
        const node = eyePool.at(i, "path");
        put(node, "d", eye.d); put(node, "transform", eye.matrix); put(node, "opacity", eye.alpha); put(node, "fill", "#000");
      });
      eyePool.trim(frame.eyes.length);
      if (frame.notch) { put(maskNotch, "cx", frame.notch.x); put(maskNotch, "cy", frame.notch.y); put(maskNotch, "r", frame.notch.r); show(maskNotch, true); } else show(maskNotch, false);

      put(bodyGroup, "opacity", frame.bodyAlpha);
      put(plate, "d", frame.bodyPath);
      putStyle(fill, "fill", style.ink);
      put(rim, "d", frame.bodyPath); show(rim, style.pale);

      const dots = frame.dots, into = frame.dotsBehind ? behindPool : frontPool, other = frame.dotsBehind ? frontPool : behindPool;
      dots.forEach((d, i) => {
        const color = d.color ?? (d.depth === undefined ? style.ink : mixHex(style.paper, style.hex, d.depth));
        if (d.d) {
          const node = into.at(i, "path");
          putStyle(node, "fill", color); put(node, "d", d.d); put(node, "opacity", d.opacity);
          put(node, "transform", `translate(${d.x} ${d.y}) rotate(${d.rot ?? 0}) scale(${RAYON})`);
        } else {
          const node = into.at(i, "circle");
          putStyle(node, "fill", color); put(node, "cx", d.x); put(node, "cy", d.y); put(node, "r", d.r); put(node, "opacity", d.opacity); put(node, "transform", "");
        }
      });
      into.trim(dots.length); other.trim(0);

      if (frame.notif) { put(notif, "cx", frame.notif.x); put(notif, "cy", frame.notif.y); put(notif, "r", frame.notif.r); show(notif, true); } else show(notif, false);

      // The rings take the bot's own colour in three steps of opacity (A7: no rainbow). The engine's wheel colours are not used.
      frame.arcs.forEach((arc, i) => {
        const g = gradient(i);
        put(g.grad, "x1", arc.grad.x1); put(g.grad, "y1", arc.grad.y1); put(g.grad, "x2", arc.grad.x2); put(g.grad, "y2", arc.grad.y2);
        g.stops.forEach((stop, k) => { putStyle(stop, "stop-color", style.ink); put(stop, "stop-opacity", RING_LEVELS[k]!); });
        const back = backArcs.at(i, "path"), front = frontArcs.at(i, "path");
        for (const [node, d] of [[back, arc.back], [front, arc.front]] as const) {
          put(node, "d", d); put(node, "stroke", `url(#${uid}-g${i})`); put(node, "stroke-width", arc.width); put(node, "opacity", arc.opacity);
        }
      });
      backArcs.trim(frame.arcs.length); frontArcs.trim(frame.arcs.length);
    },
    setWaiting(on) { show(waitingRing, on); show(waitingDot, on); put(svg, "data-waiting", on ? "true" : "false"); },
    setAura(prims) {
      if (!prims || prims.length === 0) { auraPool.trim(0); return; }
      prims.forEach((prim, i) => { const node = auraPool.at(i, prim.tag); for (const [name, value] of Object.entries(prim.attrs)) put(node, name, value); });
      auraPool.trim(prims.length);
    },
    place(tilt, dy) { put(root, "transform", tilt || dy ? `translate(0 ${dy.toFixed(2)}) rotate(${tilt.toFixed(2)})` : ""); }
  };
}
