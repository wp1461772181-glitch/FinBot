import type { Aim } from "./bloub-gaze.mjs";
export interface RowGazeHandle { pointer: { x: number; y: number; at: number } | null }
export function bindRowGaze(host: EventTarget | null | undefined, opts: { handle: RowGazeHandle; setActive: (v: boolean) => void; now: () => number; reduced: () => boolean }): () => void;
export function rowAim(pointer: RowGazeHandle["pointer"], state: string, now: number, box: { left: number; top: number; width: number; height: number } | null | undefined, view: { width: number; height: number } | null | undefined): Aim | null;
