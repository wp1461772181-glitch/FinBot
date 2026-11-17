// Small pure helpers of the data components (design 5.3, P6.1): how a signed change reads, what a status badge may be, how the
// automatic monitor's health maps to a chip.  The arithmetic and rounding live in delta.mjs and workspace-cards.mjs; nothing here
// re-implements them.
import { deltaDirection, formatDelta } from "./delta.mjs";
import { priceSummary } from "./workspace-cards.mjs";

const GLYPH_DIRECTION = { "↑": "up", "↓": "down", "→": "flat" };

/**
 * A change as `{ direction, text }`: `text` carries the sign ("+3.20", "−0.40", "0.00"), the arrow is the component's icon.
 * Rounding follows formatDelta, so "+0.001" at two digits is flat and says "0.00".  Not a number: flat and a dash.
 */
export function signedChange(value, options = {}) {
  const full = formatDelta(value, options);
  const direction = GLYPH_DIRECTION[full[0]];
  if (!direction) return { direction: "flat", text: full };
  return { direction, text: full.slice(2) };
}

/**
 * The last close and the day's change of a candle list (null when there is no close), as facts:
 * `{ close, date, direction, change: "+3.20", percent: "+1.30%", text: "+3.20 (+1.30%)" }`.  `direction` is the change's own.
 */
export function priceChange(candles) {
  const summary = priceSummary(candles);
  if (!summary) return null;
  const change = signedChange(summary.change, { digits: 2 });
  const percent = signedChange(summary.pct, { digits: 2, suffix: "%" });
  const known = summary.change !== null;
  return {
    close: summary.close, date: summary.date, direction: change.direction,
    change: known ? change.text : "", percent: known ? percent.text : "",
    text: known ? `${change.text} (${percent.text})` : "",
  };
}

/** The last `count` closes of a candle list, oldest first (what the 3-month sparkline draws; 63 sessions is about three months). */
export function recentCloses(candles, count = 63) {
  const closes = (Array.isArray(candles) ? candles : []).map((candle) => candle?.close).filter((close) => Number.isFinite(close));
  return closes.slice(-count);
}

/** The polyline of a sparkline: `closes` scaled into a `width` x `height` box (2px of air above and below), as the points attribute.  "" for fewer than two closes. */
export function sparklinePoints(closes, width, height) {
  const values = (Array.isArray(closes) ? closes : []).filter((close) => Number.isFinite(close));
  if (values.length < 2) return "";
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  return values.map((close, index) => `${round((index / (values.length - 1)) * width)},${round(height - ((close - min) / span) * (height - 4) - 2)}`).join(" ");
}
const round = (value) => Math.round(value * 100) / 100;

/** Candles the chart can draw: every price positive and the high and low really bracketing the body; oldest first, the last `count` of them. */
export function usableCandles(candles, count = 126) {
  const ok = (candle) => Boolean(candle?.trading_date) && [candle.open, candle.high, candle.low, candle.close].every((value) => Number.isFinite(value) && value > 0)
    && candle.high >= Math.max(candle.open, candle.close) && candle.low <= Math.min(candle.open, candle.close);
  return (Array.isArray(candles) ? candles : []).filter(ok).sort((a, b) => a.trading_date.localeCompare(b.trading_date)).slice(-count);
}

/** The four tones of a status badge and the two material colours (design 5.3): a fixed set, so a badge is never a free colour. */
export const BADGE_TONES = ["neutral", "progress", "success", "failure"];
export const BADGE_MATERIALS = ["opinion", "action"];
export const BADGE_KINDS = [...BADGE_TONES, ...BADGE_MATERIALS];

/** A badge kind from anything: an unknown name is neutral (a badge never invents a colour). */
export function badgeKind(kind) {
  return BADGE_KINDS.includes(kind) ? kind : "neutral";
}

/** The chip the watchlist page shows for the automatic monitor: `{ kind, phrase }` (a zh-CN phrase key; the component translates it). */
export function monitorChip(health) {
  if (health === "healthy") return { kind: "success", phrase: "监控正常" };
  if (health === "delayed") return { kind: "action", phrase: "监控延迟" };
  if (health === "degraded") return { kind: "failure", phrase: "监控异常" };
  return { kind: "neutral", phrase: "尚无记录" };
}

/** The sentence an opinion card carries in its footnote, once per page area (design 0.2).  The wording is fixed: it is shown as it is here. */
export const OPINION_DISCLAIMER = "概率未经校准，属实验性信息。仅供参考，买不买由你决定。";

export { deltaDirection };
