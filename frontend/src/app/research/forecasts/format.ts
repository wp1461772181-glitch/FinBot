import { formatDate, getLocalePreference } from "../../../i18n";

/** A saved time as a date in the reader's language (UTC, the time zone every version time is stored in); an unreadable one is shown as it is. */
export function day(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value.slice(0, 10) : formatDate(date, getLocalePreference(), "UTC");
}

/** A price as the chart's readout writes it. */
export const price = (value: number) => `$${value.toFixed(2)}`;

/** A fraction as a whole percent; "—" for anything that is not a number. */
export const pct = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "—";
export const money = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? `$${value.toFixed(2)}` : "—";
export const percent2 = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "—";
export const numberText = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
