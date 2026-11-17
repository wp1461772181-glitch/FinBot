import type { BadgeKind } from "../../../data-display.mjs";
import type { V2MonitorRun, V2MonitorStatus } from "../../../types";

export const MONITOR_HEALTHS: V2MonitorStatus["health"][];
export function monitorState(health: unknown): { id: V2MonitorStatus["health"]; kind: BadgeKind; phrase: string; headline: string; dot: "action" | "failure" | null };
export { monitorDot } from "../../monitor-dot.mjs";
export const RUN_STATUS_PHRASE: Record<V2MonitorRun["status"], string>;
export const SYMBOL_STATUS_PHRASE: Record<"succeeded" | "incomplete" | "failed", string>;
export const SYMBOL_STATUS_KIND: Record<"succeeded" | "incomplete" | "failed", BadgeKind>;
export type RunMoment = { id: "last-run" | "last-success"; kind: "run" | "success"; status: V2MonitorRun["status"]; startedAt: string | null; completedAt: string | null; nextDueAt: string | null; alsoLastSuccess: boolean };
export function runMoments(status: V2MonitorStatus | null | undefined): RunMoment[];
export type SymbolRow = { ticker: string; status: "succeeded" | "incomplete" | "failed"; error: string | null; discovered: number; created: number; queued: number };
export function symbolRows(run: V2MonitorRun | null | undefined): SymbolRow[];
export function staleHours(staleAfterSeconds: number): number;
