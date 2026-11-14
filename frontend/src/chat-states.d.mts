export type ExternalSource = { kind: "routine"; name: string; time: string | null } | { kind: "external"; name: null; time: null };
export function externalSource(userContent: unknown): ExternalSource;
export function newTurnIds(before: { turn_id?: string }[] | undefined, after: { turn_id?: string }[] | undefined): string[];
export function firstOfTurns(messages: { turn_id?: string }[] | undefined, turnIds: Iterable<string> | undefined): Map<number, string>;
export function failureNeedsSettings(code: unknown): boolean;
export type SentRequest = { content: string; pendingRequestId?: string; label?: string };
export function retryPlan<T extends { role: string; content: string; status?: string }>(messages: T[] | undefined, last: SentRequest | null | undefined): { base: T[]; content: string; pendingRequestId?: string; label?: string } | null;
export function newlyListed(previous: string[] | undefined, next: string[] | undefined): string[];
export function botIdOfLine(key: unknown): string | null;
