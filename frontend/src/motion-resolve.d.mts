import type { Hardware, MotionState } from "./motion-level.mjs";
export const LOW_CORES: number;
export const LOW_MEMORY_GB: number;
export function isLowEnd(hardware?: Hardware): boolean;
export function resolveMotionLevel(input?: { stored?: string | null; prefersReduced?: boolean; hardware?: Hardware; runtimeDowngraded?: boolean }): MotionState;
export function readHardware(nav?: unknown): Hardware;
