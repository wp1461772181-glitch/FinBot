import type { MotionLevel, MotionState } from "./motion-level.mjs";
export function saveMotionLevel(level: MotionLevel | null, storage?: Pick<Storage, "getItem" | "setItem" | "removeItem">): MotionLevel | null;
export function chooseMotion(level: MotionLevel | null): MotionState;
export function downgradeNow(): boolean;
export function revertDowngrade(): MotionState;
export const canWatch: () => boolean;
export function activateMotion(): MotionState;
