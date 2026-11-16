import assert from "node:assert/strict";
import test from "node:test";
import { fitsInside, hasProbabilities, probabilityModel, probabilityText, PROBABILITY_TONES } from "../src/probability-bar.mjs";

test("a complete triple makes three segments in the fixed order, with the fixed tones", () => {
  const model = probabilityModel({ bearish: 0.28, neutral: 0.31, bullish: 0.41 });
  assert.deepEqual(model.segments.map((s) => s.key), ["bearish", "neutral", "bullish"]);
  assert.deepEqual(model.segments.map((s) => s.tone), ["down", "muted", "up"]);
  assert.deepEqual(PROBABILITY_TONES, { bearish: "down", neutral: "muted", bullish: "up" });
  assert.deepEqual(model.segments.map((s) => s.percent), [28, 31, 41]);
  assert.deepEqual(model.segments.map((s) => Math.round(s.width)), [28, 31, 41]);
  assert.equal(model.sumsToWhole, true);
});

test("the screen-reader sentence names every class with its number", () => {
  const model = probabilityModel({ bearish: 0.28, neutral: 0.31, bullish: 0.41 });
  assert.equal(probabilityText(model), "下跌 28%，持平 31%，上涨 41%");
  assert.equal(probabilityText(model, (text) => ({ 下跌: "Bearish", 持平: "Neutral", 上涨: "Bullish" })[text], ", "), "Bearish 28%, Neutral 31%, Bullish 41%");
  assert.equal(probabilityText(null), "");
});

test("a triple that does not add to 100 is drawn as given, never rescaled", () => {
  const short = probabilityModel({ bearish: 0.2, neutral: 0.2, bullish: 0.2 });
  assert.deepEqual(short.segments.map((s) => s.percent), [20, 20, 20]);
  assert.deepEqual(short.segments.map((s) => s.width), [20, 20, 20]);
  assert.equal(short.sumsToWhole, false);
  assert.ok(Math.abs(short.sum - 60) < 1e-9);
  const long = probabilityModel({ bearish: 0.6, neutral: 0.6, bullish: 0.6 });
  assert.deepEqual(long.segments.map((s) => s.percent), [60, 60, 60]);
  assert.equal(long.sumsToWhole, false);
});

test("a segment is clamped to the track, a negative one has no width, rounding is the forecast page's", () => {
  const model = probabilityModel({ bearish: -0.1, neutral: 0.5, bullish: 1.4 });
  assert.deepEqual(model.segments.map((s) => s.width), [0, 50, 100]);
  assert.deepEqual(model.segments.map((s) => s.percent), [-10, 50, 140]);
  assert.equal(probabilityModel({ bearish: 0.125, neutral: 0.5, bullish: 0.375 }).segments[0].percent, 13);
});

test("a missing or incomplete triple is no bar at all", () => {
  for (const bad of [null, undefined, {}, { bearish: 0.3, neutral: 0.3 }, { bearish: "0.3", neutral: 0.3, bullish: 0.4 }, { bearish: Number.NaN, neutral: 0.5, bullish: 0.5 }]) {
    assert.equal(probabilityModel(bad), null);
    assert.equal(hasProbabilities(bad), false);
  }
});

test("only a segment wide enough prints its number inside", () => {
  const model = probabilityModel({ bearish: 0.05, neutral: 0.3, bullish: 0.65 });
  assert.deepEqual(model.segments.map(fitsInside), [false, true, true]);
});
