export const SLOW_FRAME_MS: number;
export const WATCH_WINDOW_MS: number;
export const GAP_MS: number;
export interface FrameWatch { step(ms: number): boolean; reset(): void; readonly span: number }
export function createFrameWatch(options?: { slow?: number; window?: number; gap?: number }): FrameWatch;
