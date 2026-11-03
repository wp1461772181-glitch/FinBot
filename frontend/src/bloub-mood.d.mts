export const CALM: string;
export const MOODS: Record<"waiting" | "tool" | "answer", string[]>;
export const HOLD: number;
export const MOOD_MORPH: number;
export function moodAt(phase: string | null | undefined, elapsed: number): string;
