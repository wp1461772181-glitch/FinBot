export const KERNEL_TOOLS: string[];
export type ProgressItem = { text: string; status: "pending" | "doing" | "done" | "failed" };
export type ProgressModel = { sentences: string[]; current: string | null; items: ProgressItem[]; doneCount: number; lookupCount: number; tierLabel: "" | "中档" | "高档" };
export function lookups<T extends { name: string }>(toolTrace: T[] | undefined | null): T[];
export function progressModel(input: { narration?: unknown; checklist?: unknown; tier?: unknown; toolTrace?: unknown; running?: boolean }): ProgressModel | null;
export function foldedLine(model: ProgressModel | null, seconds: string, t?: (text: string) => string): string[];
