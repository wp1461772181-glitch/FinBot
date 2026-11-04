import { formatDateTime, getLocalePreference, translatePhrase, useLocale } from "./i18n";
import { forecastCopy } from "./forecast-model.mjs";
import type { V2TimelineEntry, V2Workspace } from "./types";

export type ResourceState<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "error"; message: string };

export function formatTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(date, getLocalePreference(), "UTC");
}

export function modelStatusText(status: V2Workspace["joint_model_status"] | V2TimelineEntry["model_status"]) {
  return translatePhrase(forecastCopy({ model_status: status }).statusName);
}

export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/** A phrase split around values: `t` parts are phrase keys to translate, `v` parts are shown as they are. */
export function Parts({ parts }: { parts: Array<{ t: string } | { v: string }> }) {
  const { t } = useLocale();
  return <>{parts.map((part, index) => <span key={index}>{"t" in part ? t(part.t) : part.v}</span>)}</>;
}

export function ProbabilityStrip({ probabilities, label, compact = false }: { probabilities: Record<"bearish" | "neutral" | "bullish", number>; label: string; compact?: boolean }) {
  const { t } = useLocale();
  return <div className={`v2-probabilities ${compact ? "compact" : ""}`} aria-label={label}>
    {(["bearish", "neutral", "bullish"] as const).map((key) => <span key={key}><small>{t(key === "bearish" ? "跌" : key === "neutral" ? "平" : "涨")}</small><b>{Math.round(probabilities[key] * 100)}%</b></span>)}
  </div>;
}
