// The three-class probability bar, as pure functions (design 5.3, P6.1): what the segments are, how wide each is drawn, and the
// words a screen reader hears.  One drawing for the whole site; the component (components/ProbabilityBar.tsx) only paints this.
//
// The numbers are shown as the data gives them: no segment is rescaled so that the three add up to 100.  Percentages round the
// way forecast-home.mjs rounds them (`probabilityPercents`), so the bar and the old text agree digit for digit.
import { probabilityPercents } from "./forecast-home.mjs";

export const PROBABILITY_KEYS = ["bearish", "neutral", "bullish"];
/** The class names as zh-CN phrase keys (the component translates them): 下跌 / 持平 / 上涨. */
export const PROBABILITY_PHRASES = { bearish: "下跌", neutral: "持平", bullish: "上涨" };
/** Fixed colour roles: down is the `down` token, flat the muted grey, up the `up` token (both swap under red-up). */
export const PROBABILITY_TONES = { bearish: "down", neutral: "muted", bullish: "up" };

const finite = (value) => typeof value === "number" && Number.isFinite(value);

/** True when all three classes carry a finite number (anything less is "no probabilities", never a half-drawn bar). */
export function hasProbabilities(probabilities) {
  return Boolean(probabilities) && PROBABILITY_KEYS.every((key) => finite(probabilities[key]));
}

/**
 * The bar of one version, or null when the version has no (complete) probabilities.
 * `width` is the segment's share of the track in percent, as given (0 to 100, clamped per segment, never rescaled); `percent`
 * is the rounded number shown.  `sum` is the raw total in percent so a caller can say so when it is not 100.
 */
export function probabilityModel(probabilities) {
  if (!hasProbabilities(probabilities)) return null;
  const percents = probabilityPercents(probabilities);
  const segments = PROBABILITY_KEYS.map((key) => ({
    key, tone: PROBABILITY_TONES[key], phrase: PROBABILITY_PHRASES[key],
    value: probabilities[key], percent: percents[key],
    width: Math.min(100, Math.max(0, probabilities[key] * 100)),
  }));
  const sum = PROBABILITY_KEYS.reduce((total, key) => total + probabilities[key] * 100, 0);
  return { segments, sum, sumsToWhole: Math.abs(sum - 100) < 0.5 };
}

/** "下跌 28%，持平 31%，上涨 41%": the full sentence a screen reader gets.  `translate` maps a phrase key; `separator` is the locale's comma. */
export function probabilityText(model, translate = (text) => text, separator = "，") {
  if (!model) return "";
  return model.segments.map((segment) => `${translate(segment.phrase)} ${segment.percent}%`).join(separator);
}

/** Segments narrower than this (percent of the track) cannot hold their number inside; the legend and the tooltip carry it. */
export const LABEL_MIN_WIDTH = 14;

/** Whether a segment's number fits inside it on the standard size (the mini size never prints inside). */
export function fitsInside(segment) {
  return segment.width >= LABEL_MIN_WIDTH;
}
