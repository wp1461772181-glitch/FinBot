import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { defaultReplayDate, directionPhrase, evaluationKind, evaluationPhrase, isTerminalJob, jobStatusPhrase, localDate, replayFailure, replayRows, validateReplayForm } from "../src/app/research/replay/replay-model.mjs";

const baseline = JSON.parse(readFileSync(new URL("../tools/shots/fixtures/replay-bodies-baseline.json", import.meta.url), "utf8"));
const at = (y, m, d) => new Date(y, m - 1, d, 10, 0, 0);

test("the default decision day is the old page's: 32 days back, moved earlier to a weekday", () => {
  assert.equal(defaultReplayDate(at(2026, 11, 13)), baseline.form.dateValue);          // 2026-10-12, recorded from the old page
  assert.equal(defaultReplayDate(at(2026, 11, 13)), "2026-10-12");
  assert.equal(defaultReplayDate(at(2026, 11, 15)), "2026-10-14");                      // 32 days back is a Wednesday: kept
  assert.equal(defaultReplayDate(at(2026, 11, 8)), "2026-10-07");                       // also a Wednesday
  assert.equal(localDate(at(2026, 1, 5)), "2026-01-05");
});

test("a Saturday or Sunday 32 days back moves to the Friday before", () => {
  assert.equal(defaultReplayDate(at(2026, 11, 14)), "2026-10-13");
  for (let day = 1; day <= 28; day++) { const weekday = new Date(`${defaultReplayDate(at(2026, 11, day))}T12:00:00`).getDay(); assert.ok(weekday >= 1 && weekday <= 5, `day ${day}`); }
});

test("the form is checked as the old form was: a company, and a day that is set and not after today", () => {
  const today = "2026-11-13";
  for (const [name, c] of Object.entries(baseline.validation)) {
    const result = validateReplayForm({ symbol: "AAPL", date: c.value }, today);
    assert.equal(result.ok, c.sent, `${name}: the old form ${c.sent ? "sent" : "stopped"} ${JSON.stringify(c.value)}`);
  }
  assert.deepEqual(validateReplayForm({ symbol: "", date: "2026-10-12" }, today), { ok: false, field: "symbol", phrase: "请选择股票" });
  assert.deepEqual(validateReplayForm({ symbol: "AAPL", date: "" }, today), { ok: false, field: "date", phrase: "请选择历史决策日" });
  assert.deepEqual(validateReplayForm({ symbol: "AAPL", date: "2026-11-14" }, today), { ok: false, field: "date", phrase: "历史决策日不能晚于今天" });
});

test("the replays are the historical cohort's versions, newest decision day first", () => {
  const v = (id, decision_at) => ({ id, decision_at });
  const evaluation = { cohorts: { historical_research: { roots: [{ versions: [v("a", "2026-09-02T02:00:00Z")] }, { versions: [v("b", "2026-09-16T02:00:00Z"), v("c", "2026-08-15T02:00:00Z")] }] } } };
  assert.deepEqual(replayRows(evaluation).map((r) => r.id), ["b", "a", "c"]);
  assert.deepEqual(replayRows(null), []);
  assert.deepEqual(replayRows({ cohorts: {} }), []);
});

test("evaluation, direction and job words are the old page's, and only a failed evaluation is a failure", () => {
  assert.deepEqual(["pending", "succeeded", "blocked_price", "failed", "?"].map(evaluationPhrase), ["等待评估", "已完成评估", "行情不足", "评估失败", "待评估"]);
  assert.deepEqual(["pending", "succeeded", "blocked_price", "failed"].map(evaluationKind), ["neutral", "success", "neutral", "failure"]);
  assert.deepEqual(["bearish", "neutral", "bullish", "x"].map(directionPhrase), ["看跌", "中性", "看涨", "x"]);
  assert.deepEqual(["queued", "running", "succeeded", "succeeded_no_change", "blocked_data", "failed"].map(jobStatusPhrase), ["等待处理", "正在生成", "回放已生成", "已有相同回放", "资料不足，回放未生成", "回放任务失败"]);
  assert.deepEqual(["queued", "running", "succeeded", "succeeded_no_change", "blocked_data", "failed"].map(isTerminalJob), [false, false, true, true, true, true]);
});

test("a failed replay says its status words and the reason: the failure table's sentence, else the code as it is", () => {
  const timeout = replayFailure({ status: "failed", error: { type: "forecast_provider_timeout" } });
  assert.equal(timeout.title, baseline.failures["failed-timeout"].text.includes("回放任务失败") ? "回放任务失败" : "?");
  assert.equal(timeout.code, "forecast_provider_timeout");
  assert.ok(timeout.reason && timeout.reason.length > 4);
  const unknown = replayFailure({ status: "failed", error: { type: "something_new" } });
  assert.deepEqual([unknown.code, unknown.reason], ["something_new", null]);
  assert.equal(replayFailure({ status: "blocked_data", error: { type: "insufficient_price_history" } }).title, "资料不足，回放未生成");
  assert.deepEqual(replayFailure({ status: "failed", error: null }), { title: "回放任务失败", code: null, reason: null });
});
