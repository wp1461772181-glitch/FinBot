export type UnverifiedLine = { line: string; reason: string; numbers: string[]; ordinal?: number; snippet?: string };
export type UnverifiedLabels = { insufficient: string; numbers: string; reason: (code: string) => string; hint?: (item: UnverifiedLine) => string | null };

export const REASON_KEYS: Record<string, string>;
export const HINT_KEYS: Record<string, string>;
export function hintText(item: UnverifiedLine | null | undefined, t?: (text: string) => string): string | null;
export const DEFAULT_REASON_KEY: string;
export function lineKey(line: string | null | undefined): string;
export function normalizeUnverified(items: unknown): UnverifiedLine[];
export function reasonKey(reason: string | null | undefined): string;
export function matchLines(content: string | null | undefined, items: unknown): number[];
export function markUnverified(content: string | null | undefined, items: unknown, labels: UnverifiedLabels): string;
export function parseFlagHref(href: string | null | undefined): { kind: "insufficient" | "numbers"; index: number } | null;
export function plainSentence(line: string | null | undefined): string;
export function followUpQuestion(line: string | null | undefined): string;
