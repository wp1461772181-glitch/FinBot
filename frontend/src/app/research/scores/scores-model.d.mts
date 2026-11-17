import type { V2ModelEvaluationCohort } from "../../../types";

export const RULE_TEXT: string;
export const BASELINE_EXPLAINER: string;
export const BASELINE_NAME: string;
export function modelStatusPhrase(status: string): string;
export function timeModePhrase(mode: string): string;
export function cohortStatusPhrase(status: string): string;
export type CohortGroup = { key: "llm" | "earlier"; title: string; note: string; items: V2ModelEvaluationCohort[] };
export function cohortGroups(cohorts: V2ModelEvaluationCohort[]): CohortGroup[];
export function mean(values: Array<number | null | undefined>): number | null;
export function cohortAverages(cohort: V2ModelEvaluationCohort): { brier: number | null; logLoss: number | null };
export function fixed3(value: unknown): string | null;
export type Bars = { model: number; baseline: number } | null;
export type CohortView = {
  available: boolean;
  sample: V2ModelEvaluationCohort["sample"];
  floor: number;
  brier: string | null;
  logLoss: string | null;
  banner: string | null;
  comparison: null | {
    pairedRootCount: number;
    baselineUnavailableRootCount: number;
    brier: { model: number | null; baseline: number | null; bars: Bars };
    logLoss: { model: number | null; baseline: number | null; bars: Bars };
  };
};
export function cohortView(cohort: V2ModelEvaluationCohort, minimumScoredRoots: number): CohortView;
export function compareBars(model: unknown, baseline: unknown): Bars;
export function cohortKey(cohort: V2ModelEvaluationCohort, index: number): string;
