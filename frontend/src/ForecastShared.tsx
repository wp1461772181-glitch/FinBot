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
