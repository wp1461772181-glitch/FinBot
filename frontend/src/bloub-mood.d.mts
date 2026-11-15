export const CALM: string;
export const MOODS: Record<"waiting" | "tool" | "answer", string[]>;
export const HOLD: number;
export const MOOD_MORPH: number;
export type MoodPhase = "waiting" | "tool" | "answer" | "listen" | "verify" | "hold";
export const MOODS_BY_ARCHETYPE: Record<"lead" | "tracker" | "sentinel" | "reader" | "generalist", Record<MoodPhase, string[]>>;
export function moodAt(phase: string | null | undefined, elapsed: number, archetype?: string | null): string;
