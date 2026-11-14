import type { AgentChatLifecycle } from "./agentChatLifecycle.js";
export function lineKey(bot: { id?: string } | null | undefined, conversationId?: string | null): string;
export function loadDraft(line: string, storage?: Pick<Storage, "getItem">): string;
export function saveDraft(line: string, text: string, storage?: Pick<Storage, "setItem" | "removeItem">): void;
export type LineState<M = unknown> = { messages: M[]; state: string; status: string; conversationId: string | null; historyHasMore: boolean; historyBefore: number | null; restoring: boolean; draft: string; loaded: boolean; unseen: boolean; lifecycle: AgentChatLifecycle };
export function createLineStore<M = unknown>(): { get(line: string): LineState<M>; update(line: string, patch: Partial<LineState<M>>): LineState<M>; setActive(line: string | null): void; active(): string | null; all(): [string, LineState<M>][]; running(): string[]; unseen(): string[]; waiting(): string[]; markSeen(line: string): void };
