import type { BadgeKind } from "../../../data-display.mjs";
import type { V2EvaluationResponse, V2EvaluationVersion, V2ForecastJob } from "../../../types";

export function localDate(date: Date): string;
export function defaultReplayDate(now?: Date): string;
export type ReplayCheck = { ok: true } | { ok: false; field: "symbol" | "date"; phrase: string };
export function validateReplayForm(form: { symbol: string; date: string }, today: string): ReplayCheck;
export function replayRows(evaluation: V2EvaluationResponse | null | undefined): V2EvaluationVersion[];
export function evaluationPhrase(status: string): string;
export function evaluationKind(status: string): BadgeKind;
export function directionPhrase(direction: string): string;
export function modelPhrase(status: string): string;
export function jobStatusPhrase(status: string): string;
export function isTerminalJob(status: V2ForecastJob["status"]): boolean;
export function replayFailure(job: V2ForecastJob): { title: string; code: string | null; reason: string | null };
