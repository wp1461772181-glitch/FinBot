export interface Look { yaw: number; pitch: number; mix: number; spin: number; wander: number }
export interface Aim { nx: number; ny: number }
export const YAW_MAX: number, PITCH_MAX: number, PITCH: number, ENGAGE_TIME: number, POINTER_STALE: number, TOUR_TIME: number, SPIN: number;
export function easeOutQuint(t: number): number;
export function easeInOutCubic(t: number): number;
export function aimFromPointer(pointer: { x: number; y: number } | null | undefined, box: { left: number; top: number; width: number; height: number } | null | undefined, view: { width: number; height: number } | null | undefined): Aim | null;
export function followLook(aim: Aim, engage?: number): Look;
export function pointerFresh(lastMoveAt: number | null | undefined, now: number): boolean;
export function tourLook(t: number): Look;
