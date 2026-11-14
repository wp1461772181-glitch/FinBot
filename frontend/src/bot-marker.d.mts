export type BotMarker = { kind: "running" | "waiting" | "unread" | "none"; ring: boolean; dot: boolean; word: "running" | "waiting" | null; count: number };
export function isWaiting(bot: { id?: string; pending?: number } | null | undefined, waitingLines?: string[]): boolean;
export function botMarker(input?: { running?: boolean; waiting?: boolean; unread?: number; active?: boolean }): BotMarker;
export function countLabel(count: number): string;
