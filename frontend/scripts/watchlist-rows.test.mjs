import assert from "node:assert/strict";
import test from "node:test";
import { createPool, latestForecast, restoreAt, watchRow } from "../src/watchlist-rows.mjs";
import { checkWatchAdd } from "../src/watchlist-add.mjs";

const forecast = (id, symbol, decision_at, extra = {}) => ({ id, symbol, decision_at, target_end_date: "2026-12-31", model_status: "experimental_llm", latest_version_no: 3,
  decider: { actual_model: "gpt-6.1-terra" }, probabilities: { bearish: 0.2, neutral: 0.4, bullish: 0.4 }, expired: false, evaluation: null, ...extra });
const candle = (close, i) => ({ trading_date: `2026-11-${String(i + 1).padStart(2, "0")}`, open: close, high: close, low: close, close, volume: 1 });

test("the row shows the newest forecast of its own company", () => {
  const rows = [forecast("a", "AAPL", "2026-10-01T00:00:00Z"), forecast("b", "AAPL", "2026-11-01T00:00:00Z"), forecast("c", "TSLA", "2026-11-05T00:00:00Z")];
  assert.equal(latestForecast(rows, "AAPL").id, "b");
  assert.equal(latestForecast(rows, "aapl").id, "b");
  assert.equal(latestForecast(rows, "NVDA"), null);
  assert.equal(latestForecast(null, "AAPL"), null);
});

test("a row is made of what has been read; what has not is null, not a guess", () => {
  const bare = watchRow({ symbol: "AAPL" });
  assert.deepEqual(bare, { symbol: "AAPL", price: null, closes: [], forecast: null, materialTotal: null });
  const full = watchRow({ symbol: "AAPL", forecast: forecast("b", "AAPL", "2026-11-01T00:00:00Z"), candles: [candle(100, 0), candle(103, 1)], materialTotal: 12 });
  assert.equal(full.price.text, "+3.00 (+3.00%)");
  assert.deepEqual(full.closes, [100, 103]);
  assert.equal(full.forecast.id, "b");
  assert.equal(full.forecast.versionNo, 3);
  assert.equal(full.forecast.targetDate, "2026-12-31");
  assert.equal(full.forecast.model, "gpt-6.1-terra");
  assert.equal(full.materialTotal, 12);
});

test("a forecast without probabilities still makes a row, with its model status and no bar", () => {
  const row = watchRow({ symbol: "AAPL", forecast: forecast("b", "AAPL", "2026-11-01T00:00:00Z", { probabilities: null, model_status: "research_only" }) });
  assert.equal(row.forecast.probabilities, null);
  assert.equal(row.forecast.status, "research_only");
});

test("read with no candles is not the same as not read", () => {
  assert.equal(watchRow({ symbol: "X", candles: [] }).price, null);
  assert.deepEqual(watchRow({ symbol: "X", candles: [] }).closes, []);
});

test("the pool never runs more tasks at once than its size and keeps the order asked", async () => {
  const pool = createPool(2);
  let running = 0, peak = 0;
  const started = [];
  const task = (name) => async () => { started.push(name); running += 1; peak = Math.max(peak, running); await new Promise((r) => setTimeout(r, 5)); running -= 1; return name; };
  const results = await Promise.all(["a", "b", "c", "d", "e"].map((name) => pool.run(task(name))));
  assert.deepEqual(results, ["a", "b", "c", "d", "e"]);
  assert.deepEqual(started, ["a", "b", "c", "d", "e"]);
  assert.equal(peak, 2);
  assert.equal(pool.active, 0);
});

test("a task whose signal is aborted before it starts never runs; one that fails frees its slot", async () => {
  const pool = createPool(1);
  const controller = new AbortController();
  let ran = false;
  const first = pool.run(() => new Promise((r) => setTimeout(() => r("first"), 10)));
  const second = pool.run(() => { ran = true; return "second"; }, controller.signal);
  controller.abort();
  await assert.rejects(second, { name: "AbortError" });
  assert.equal(await first, "first");
  assert.equal(ran, false);
  await assert.rejects(pool.run(() => Promise.reject(new Error("boom"))), /boom/);
  assert.equal(await pool.run(() => "after"), "after");
  await assert.rejects(pool.run(() => "x", controller.signal), { name: "AbortError" });
});

test("adding a code: normalised, or the sentence the research bar has always said", () => {
  assert.deepEqual(checkWatchAdd(" amd ", ["AAPL"]), { ok: true, ticker: "AMD" });
  assert.deepEqual(checkWatchAdd("brk-b", ["AAPL"]), { ok: true, ticker: "BRK.B" });
  assert.deepEqual(checkWatchAdd("12!", ["AAPL"]), { ok: false, error: "请输入有效的美股代码，例如 AMD 或 BRK.B。" });
  assert.deepEqual(checkWatchAdd("aapl", ["AAPL"]), { ok: false, error: "该代码已在关注列表中。" });
  const full = Array.from({ length: 30 }, (_, i) => `A${String.fromCharCode(65 + (i % 26))}${i > 25 ? "B" : ""}`);
  assert.equal(new Set(full).size, 30);
  assert.deepEqual(checkWatchAdd("ZZZ", full), { ok: false, error: "关注列表最多保存 30 个代码。" });
});

test("undoing a removal puts the code back where it was, and never twice or past the limit", () => {
  const before = ["AAPL", "TSLA", "NVDA"];
  const after = before.filter((s) => s !== "TSLA");
  assert.deepEqual(restoreAt(after, "TSLA", 1), before);
  assert.deepEqual(restoreAt(after, "TSLA", 99), ["AAPL", "NVDA", "TSLA"]);
  assert.deepEqual(restoreAt(after, "TSLA", -3), ["TSLA", "AAPL", "NVDA"]);
  assert.equal(restoreAt(before, "TSLA", 1), before);
  assert.equal(restoreAt(["A", "B"], "C", 0, 2).length, 2);
});
