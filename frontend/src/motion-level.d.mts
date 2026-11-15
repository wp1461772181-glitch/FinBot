export type MotionLevel = "full" | "lite" | "off";
export type MotionSource = "system" | "user" | "auto-device" | "auto-runtime" | "default";
export interface MotionState { level: MotionLevel; source: MotionSource }
export interface Hardware { cores?: number; memoryGB?: number; saveData?: boolean }
export const MOTION_KEY: string;
export const LEVELS: MotionLevel[];
export function storedMotionLevel(storage?: Pick<Storage, "getItem">): MotionLevel | null;
export function startMotion(): MotionState;
