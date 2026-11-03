export function pollDelay(options?: { hidden?: boolean; failures?: number }): number;
type Msg = { role: string; content: string; turn_id?: string };
export function mergeNewTurns<M extends Msg>(local: M[], serverTail: M[]): { messages: M[]; added: number; gap: boolean };
export function planTailSync<M extends Msg>(lineState: { messages: M[]; state: string; restoring: boolean; conversationId: string | null } | null | undefined, serverTail: M[], conversationId: string | null): { messages: M[]; added: number } | null;
