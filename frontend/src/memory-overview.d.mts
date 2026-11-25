import type { MemoryCounts, MemoryJob, MemoryWatch, OverviewCompany } from "./api/memory-overview";
import type { OwnerViewVersion } from "./api/owner-views";
/** A company of the views section: `versions` newest first, `history` those other than the current one. */
export type ViewGroup = OverviewCompany & { history: OwnerViewVersion[] };
export function summaryLine(counts: MemoryCounts | null | undefined): Array<{ key: keyof MemoryCounts; label: string; value: number }>;
export function viewGroups(views: OverviewCompany[] | null | undefined): { current: ViewGroup[]; former: ViewGroup[] };
export function typedOnPage(version: { conversation_id?: string | null } | null | undefined): boolean;
export function viewWriteError(status: number | undefined, detail?: unknown): string;
export function jobLine(job: MemoryJob | null | undefined, locale?: string, now?: Date): string;
export function jobOutcome(job: Pick<MemoryJob, "last_outcome" | "last_reason"> | null | undefined, locale?: string): string;
export function exportFilename(format: string, now?: Date): string;
export type WatchPlanRow = { symbol: string; prices: Array<{ key: string; label: string; value: string }>; text: string };
export type WatchRoutineRow = { id: string; name: string; enabled: boolean; scope: string; scopeLabel: string; symbols: string[]; contents: Array<{ key: string; label: string; detail?: string }>; next: string };
export type WatchRows = { plans: WatchPlanRow[]; routines: WatchRoutineRow[]; queue: string[] | null; note: string };
export function watchRows(watch: MemoryWatch | null | undefined, locale?: string, now?: Date): WatchRows;
