export type UnverifiedLine = { line: string; reason: string; numbers: string[] };
export type UnverifiedLabels = { insufficient: string; numbers: string; reason: (code: string) => string };

export const REASON_KEYS: Record<string, string>;
export const DEFAULT_REASON_KEY: string;
export function lineKey(line: string | null | undefined): string;
export function normalizeUnverified(items: unknown): UnverifiedLine[];
export function reasonKey(reason: string | null | undefined): string;
export function matchLines(content: string | null | undefined, items: unknown): number[];
export function markUnverified(content: string | null | undefined, items: unknown, labels: UnverifiedLabels): string;
export function parseFlagHref(href: string | null | undefined): { kind: "insufficient" | "numbers"; index: number } | null;
export function plainSentence(line: string | null | undefined): string;
export function followUpQuestion(line: string | null | undefined): string;
