import type { Look } from "../bloub-gaze.mjs";
/** The gaze kind (bloub-director's `view.gaze`) while a tool runs, for an aura variant. */
export function toolGaze(variant: string | null | undefined): "side" | "side-left" | "below" | "sweep";
/** Seconds one lap of the moving point takes, by variant (only the variants that have one). */
export const SWEEP_PERIOD: Record<string, number>;
/** The look toward a point at angle `a` (0 = up, clockwise), in eighths of a turn. */
export function sweepLook(a: number): Look;
export function sweepAngle(variant: string | null | undefined, t: number, turn?: number): number;
