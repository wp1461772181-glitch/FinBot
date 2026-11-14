export type HoldState = { phase: "idle" | "holding" | "armed" | "done"; since: number; via: "pointer" | "key" | "click" | null };
export type HoldEvent = { type: "press"; via: "pointer" | "key"; now: number } | { type: "release"; now?: number } | { type: "tick"; now: number } | { type: "click"; now: number } | { type: "blur" };
export const HOLD_MS: number;
export const ARM_MS: number;
export function initialHold(): HoldState;
export function holdProgress(state: HoldState, now: number, holdMs?: number): number;
export function stepHold(state: HoldState, event: HoldEvent, options?: { holdMs?: number; armMs?: number; reducedMotion?: boolean }): HoldState;
