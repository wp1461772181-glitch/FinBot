export type AuraPhase = "idle" | "listen" | "think" | "tool" | "verify" | "answer" | "hold" | "done" | "partial" | "error" | "cancel" | "unread" | "sleep" | "offline";
export type AuraTone = 0 | 1 | 2 | "ink" | "amber" | "danger";
export type AuraEasing = "smooth" | "spring" | "step";
/** The finished shape of a turn: a closed ring / line, a ring with a gap, a broken one. */
export type AuraForm = "closed" | "gap" | "broken";
interface Base { key: string; opacity: number; tone: AuraTone; unit?: number; form?: AuraForm; anim?: "slow-blink"; w?: number; dash?: [number, number]; dashOffset?: number }
export type AuraPrim = Base & (
  | { kind: "line"; x1: number; y1: number; x2: number; y2: number }
  | { kind: "arc"; cx: number; cy: number; r: number; a0: number; a1: number }
  | { kind: "dot"; cx: number; cy: number; r: number }
  | { kind: "rect"; x: number; y: number; w: number; h: number }
  | { kind: "path"; d: string });
/** What an aura function takes.  `t` is on the bot's own clock (tempo multiplied in); `ages` (real seconds since each unit came back) and `born` (the turn's own clock then) only animate arrivals and place marks. */
export interface AuraInput {
  phase: AuraPhase; t: number; units: number; tier: "M" | "L" | "S" | "XS" | string; R: number;
  settled?: { phase: AuraPhase; units: number; t: number } | null;
  outcome?: string | null; waiting?: boolean; reduced?: boolean; verified?: boolean; easing?: AuraEasing | string; tempo?: number;
  ages?: ReadonlyArray<number>; born?: ReadonlyArray<number>; turn?: number;
}
export type AuraFn = (input: AuraInput) => AuraPrim[];
export const TAU: number, PHASES: ReadonlyArray<AuraPhase>, TONES: ReadonlyArray<AuraTone>, TRANSITION: number, ARRIVE: number, TONE_LEVELS: readonly [number, number, number];
export const END: Record<"done" | "partial" | "error", { close: number; hold: number; fade: number }>;
export function endLength(phase: string): number;
export function ease(kind: string, x: number): number;
export function smooth(x: number): number;
export function clamp(x: number, lo?: number, hi?: number): number;
export function lerp(a: number, b: number, p: number): number;
export function polar(r: number, a: number): [number, number];
export function normalize(input: unknown, limits: { cap: number; capM?: number }): any;
export function visibility(s: any): number;
export function endBeat(s: any): { p: number; fade: number; over: boolean };
export function closingArc(i: number, n: number, c0: number, hw0: number, p: number, gap?: number, start?: number): [number, number];
export function rowShare(i: number, n: number, gap?: boolean): [number, number];
