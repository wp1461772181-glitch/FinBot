export const STREAM_IDLE_MS: number;
export const BACKGROUND_WAIT_MS: number;

/** The background turn this page is showing: why, and the turn it stands for (null when unknown). */
export type Background = { conversationId: string | null; turnId: string | null; reason: "dropped" | "stop_unreachable" | "busy" | "restored"; at: number };
/** The local note for a turn running on the server; `gone` means the server has said it is no longer running. */
export type DetachedRecord = { turnId: string; question: string; at: number; gone?: boolean };
export type StorageLike = { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void };
export type MessageLike = { role?: string; status?: string; turn_id?: string };

export function streamBreak(input: { aborted: boolean; detachable: boolean; sawTerminal: boolean; closed: boolean }): "stopped" | "ended" | "detached" | "failed";
export function nextChunk<T>(reader: { read(): Promise<T>; cancel(reason?: unknown): Promise<void> }, options: { idleMs: number; watch: boolean }): Promise<T | { idle: true }>;
export function completeTurnsOnly<M extends MessageLike>(messages: ReadonlyArray<M> | null | undefined): M[];
export function arrivalSplit(input: { arrived: string[]; messages: ReadonlyArray<MessageLike>; ownTurnId: string | null | undefined; background: Background | null }): { away: string[]; external: string[]; clearBackground: boolean; ownArrived: boolean };
export function detachedKey(cid: string): string;
export function saveDetached(storage: StorageLike | null | undefined, cid: string, record: DetachedRecord): void;
export function loadDetached(storage: StorageLike | null | undefined, cid: string): DetachedRecord | null;
export function dropDetached(storage: StorageLike | null | undefined, cid: string): void;
export function markDetachedGone(storage: StorageLike | null | undefined, cid: string): void;
export function resumePlan(input: { marker: DetachedRecord | null; messages: ReadonlyArray<MessageLike>; now: number }): { kind: "none" } | { kind: "arrived"; turnId: string; away: boolean } | { kind: "running"; turnId: string; question: string; at: number } | { kind: "expired" } | { kind: "gone" };
export function backgroundExpired(background: Background | null, now: number): boolean;
export function restoredBeforeSend(beforeList: unknown, messages: unknown): boolean;
