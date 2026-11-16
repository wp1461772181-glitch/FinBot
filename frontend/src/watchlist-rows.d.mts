import type { ForecastRowLike } from "./forecast-home.mjs";
import type { DeltaDirection } from "./delta.mjs";
export function latestForecast<T extends ForecastRowLike>(rows: T[], symbol: string): T | null;
export type WatchRow = {
  symbol: string;
  price: { close: number; date: string; direction: DeltaDirection; change: string; percent: string; text: string } | null;
  closes: number[];
  forecast: { id: string; versionNo: number; targetDate: string | null; status: string; probabilities: Record<"bearish" | "neutral" | "bullish", number> | null; model: string | null; decisionAt: string } | null;
  materialTotal: number | null;
};
export function watchRow(input: { symbol: string; forecast?: (ForecastRowLike & { probabilities?: unknown }) | null; candles?: unknown[] | null; materialTotal?: number | null }): WatchRow;
export function createPool(size?: number): { run<T>(task: () => Promise<T> | T, signal?: AbortSignal): Promise<T>; readonly active: number; readonly waiting: number };
export function restoreAt(items: string[], ticker: string, index: number, max?: number): string[];
