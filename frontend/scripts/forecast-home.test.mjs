import assert from "node:assert/strict";
import test from "node:test";
import {
  attentionLabel, filterRows, filterScopes, forecastBySymbol, formalRowModel, judgmentLane, judgmentResultText, judgmentRowModel,
  sortForAttention, splitDelivered, symbolMark, symbolsWithBoth,
} from "../src/forecast-home.mjs";

const NOW = new Date("2026-11-04T12:00:00Z");

function row(id, symbol, extra = {}) {
  return {
    id, symbol, decision_at: "2026-10-01T20:00:00Z", target_end_date: "2026-12-15", expired: false, model_status: "experimental_llm",
    latest_version_no: 1, decider: { actual_model: "glm-5.3-flash" }, probabilities: { bearish: 0.33, neutral: 0.34, bullish: 0.33 },
    evaluation: null, ...extra,
  };
}

function judgment(id, symbol, extra = {}) {
  return {
    id, symbol, accepted_at: "2026-10-30T20:05:00Z", direction: "up", confidence: "high", after_hours: 0.126, model: "glm-5.3-flash",
    model_source: "followup", delivered: true, outcome: { status: "pending", reaction: null, sigma: null }, ...extra,
  };
}

test("rows sort by attention tier: running or failed work, expiring soon, just evaluated, then the rest", () => {
  const rows = [
    row("rest-old", "OLD", { decision_at: "2026-09-01T20:00:00Z", target_end_date: "2026-12-30" }),
    row("evaluated", "EVAL", { expired: true, target_end_date: "2026-11-01", evaluation: { status: "succeeded" } }),
    row("expiring", "SOON", { target_end_date: "2026-11-08" }),
    row("alerted", "JOB"),
    row("rest-new", "NEW", { decision_at: "2026-10-20T20:00:00Z", target_end_date: "2026-12-30" }),
  ];
  const sorted = sortForAttention(rows, [{ symbol: "JOB", status: "failed" }], NOW);
  assert.deepEqual(sorted.map((item) => item.row.id), ["alerted", "expiring", "evaluated", "rest-new", "rest-old"]);
  assert.deepEqual(sorted.map((item) => item.tier), [1, 2, 3, 5, 5]);
});

test("expiring rows sort soonest first, and ties break on decision time then id", () => {
  const rows = [
    row("b", "B", { target_end_date: "2026-11-10" }),
    row("a", "A", { target_end_date: "2026-11-06" }),
    row("t2", "T2", { target_end_date: "2026-12-30" }),
    row("t1", "T1", { target_end_date: "2026-12-30" }),
  ];
  const ids = sortForAttention(rows, [], NOW).map((item) => item.row.id);
  assert.deepEqual(ids, ["a", "b", "t1", "t2"]);
});

test("an expired row without a finished evaluation is an ordinary row, and an old evaluation is not 'just' evaluated", () => {
  const rows = [
    row("expired-unscored", "X", { expired: true, target_end_date: "2026-11-02", evaluation: null }),
    row("expired-old", "Y", { expired: true, target_end_date: "2026-09-01", evaluation: { status: "succeeded" } }),
    row("invalid", "Z", { expired: null, target_end_date: null }),
  ];
  assert.deepEqual(sortForAttention(rows, [], NOW).map((item) => item.tier), [5, 5, 5]);
});

test("sorting does not mutate its input and tolerates empty input", () => {
  const rows = [row("a", "A"), row("b", "B", { decision_at: "2026-10-20T20:00:00Z" })];
  const copy = JSON.stringify(rows);
  sortForAttention(rows, [], NOW);
  assert.equal(JSON.stringify(rows), copy);
  assert.deepEqual(sortForAttention([], [], NOW), []);
  assert.deepEqual(sortForAttention(undefined, undefined, NOW), []);
});

test("attention labels exist for the flagged tiers only", () => {
  assert.ok(attentionLabel(1) && attentionLabel(2) && attentionLabel(3));
  assert.equal(attentionLabel(5), "");
});

test("filters keep nothing under 持仓 when holdings are empty, and match symbols case-insensitively", () => {
  const rows = [row("a", "AMD"), row("b", "NVDA")];
  assert.deepEqual(filterRows(rows, "holdings", [], ["AMD"]), []);
  assert.deepEqual(filterRows(rows, "holdings", ["amd"], []).map((item) => item.id), ["a"]);
  assert.deepEqual(filterRows(rows, "queue", [], ["NVDA"]).map((item) => item.id), ["b"]);
  assert.deepEqual(filterRows(rows, "queue", [], []), []);
  assert.equal(filterRows(rows, "all", [], []).length, 2);
});

test("without a portfolio the filters offer only 全部 and 研究队列", () => {
  assert.deepEqual(filterScopes(false), ["all", "queue"]);
  assert.deepEqual(filterScopes(true), ["all", "holdings", "queue"]);
});

test("a symbol is marked 持仓 before 队列, and unmarked when neither", () => {
  assert.equal(symbolMark("AMD", ["AMD"], ["AMD"]), "持仓");
  assert.equal(symbolMark("AMD", [], ["amd"]), "队列");
  assert.equal(symbolMark("AMD", [], []), null);
});

test("every judgment result state has its sentence, and pending waits for the first session close", () => {
  assert.equal(judgmentResultText({ status: "pending" }), "等待首个交易日收盘");
  assert.equal(judgmentResultText({ status: "matched" }), "方向相符");
  assert.equal(judgmentResultText({ status: "mismatched" }), "方向不符");
  assert.equal(judgmentResultText({ status: "no_marked_move" }), "未出现明显波动");
  assert.match(judgmentResultText({ status: "not_applicable" }), /不计结果/);
  assert.equal(judgmentResultText(undefined), "等待首个交易日收盘");
});

test("a judgment row model carries no probability, and its only percentage is the after-hours move it knew", () => {
  const model = judgmentRowModel(judgment("j1", "AMD"));
  assert.equal("probabilities" in model, false);
  const { afterHours, ...rest } = model;
  assert.doesNotMatch(JSON.stringify(rest), /%/);
  assert.deepEqual(afterHours.parts, [{ t: "判断时已知盘后" }, { v: " +12.6%" }]);
  assert.equal(model.direction, "偏涨");
  assert.equal(model.confidence, "把握：高");
  assert.equal(model.typeLabel, "财报判断 · 轻量 · 未经盲测");
  assert.equal(model.hash, "#forecast/judgment/j1");
});

test("judgment direction words, missing after-hours, and a first-stage model", () => {
  assert.equal(judgmentRowModel(judgment("j", "A", { direction: "down" })).direction, "偏跌");
  assert.equal(judgmentRowModel(judgment("j", "A", { direction: "unclear" })).direction, "没有明确方向");
  assert.equal(judgmentRowModel(judgment("j", "A", { after_hours: null })).afterHours, null);
  assert.equal(judgmentRowModel(judgment("j", "A", { after_hours: -0.031 })).afterHours.parts[1].v, " -3.1%");
  assert.equal(judgmentRowModel(judgment("j", "A", { model_source: "first_stage" })).modelFirstStage, true);
  assert.equal(judgmentRowModel(judgment("j", "A", { model: null })).model, null);
});

test("a formal row model has probabilities and a version, and never a direction word or a confidence", () => {
  const model = formalRowModel(row("r1", "AMD"), { holdings: ["AMD"], queue: [] });
  assert.doesNotMatch(JSON.stringify(model), /偏涨|偏跌|把握/);
  assert.deepEqual(model.probabilities, { bearish: 0.33, neutral: 0.34, bullish: 0.33 });
  assert.equal(model.mark, "持仓");
  assert.equal(model.model, "glm-5.3-flash");
  assert.equal(model.hash, "#forecast/r1");
  assert.deepEqual(model.titleParts, [{ t: "正式预测 · 第" }, { v: " 1 " }, { t: "版" }]);
});

test("a formal row from an old version without a recorded model keeps the model empty, not guessed", () => {
  assert.equal(formalRowModel(row("r", "A", { decider: {} })).model, null);
  assert.equal(formalRowModel(row("r", "A", { decider: undefined })).model, null);
  assert.equal(formalRowModel(row("r", "A", { probabilities: null })).probabilities, null);
});

test("a judgments call rejected with 401 or 403 hides the lane without an error; other failures are errors", () => {
  assert.deepEqual(judgmentLane({ status: "rejected", reason: { status: 401 } }), { lane: "hidden" });
  assert.deepEqual(judgmentLane({ status: "rejected", reason: { status: 403 } }), { lane: "hidden" });
  assert.deepEqual(judgmentLane({ status: "rejected", reason: { status: 500 } }), { lane: "error" });
  assert.deepEqual(judgmentLane({ status: "rejected", reason: new Error("network") }), { lane: "error" });
  assert.deepEqual(judgmentLane({ status: "fulfilled", value: [] }), { lane: "ready", judgments: [] });
  const list = [judgment("j", "A")];
  assert.deepEqual(judgmentLane({ status: "fulfilled", value: list }), { lane: "ready", judgments: list });
});

test("sent and skipped judgments are split in order, and both are kept", () => {
  const list = [judgment("a", "A"), judgment("b", "B", { delivered: false }), judgment("c", "C"), judgment("d", "D", { delivered: false })];
  const { delivered, skipped } = splitDelivered(list);
  assert.deepEqual(delivered.map((item) => item.id), ["a", "c"]);
  assert.deepEqual(skipped.map((item) => item.id), ["b", "d"]);
  assert.deepEqual(splitDelivered(undefined), { delivered: [], skipped: [] });
});

test("one list is grouped by symbol for the queue cards, newest decision first", () => {
  const groups = forecastBySymbol([
    row("a1", "amd", { decision_at: "2026-09-01T20:00:00Z" }),
    row("n1", "NVDA"),
    row("a2", "AMD", { decision_at: "2026-10-20T20:00:00Z" }),
  ]);
  assert.deepEqual(groups.get("AMD").map((item) => item.id), ["a2", "a1"]);
  assert.deepEqual(groups.get("NVDA").map((item) => item.id), ["n1"]);
  assert.equal(groups.get("TSLA"), undefined);
  assert.equal(forecastBySymbol(undefined).size, 0);
});

test("symbols that have both a forecast and a judgment are found", () => {
  const both = symbolsWithBoth([row("r", "AMD"), row("s", "NVDA")], [judgment("j", "AMD"), judgment("k", "TSLA")]);
  assert.deepEqual([...both], ["AMD"]);
});
