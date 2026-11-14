import test from "node:test";
import assert from "node:assert/strict";
import { barModel, legacyToolChips, stepChips, toolResultSummary } from "../src/process-steps.mjs";
import { normalizeTrace } from "../src/turn-flow.mjs";

const node = (id, kind, fields = {}) => ({ id, kind, status: "done", after: [], start_ms: 0, ms: 600, output: null, ...fields });
const TRACE = normalizeTrace([
  node("n1", "input", { output: { question: "q" } }),
  node("n2", "classify", { output: { category: "A" } }),
  node("n3", "decide", { step: 1, output: { calls: ["query_sec_filings"] } }),
  node("n4", "tool", { name: "query_sec_filings", after: ["n3"], output: { ok: true, count: 3 } }),
  node("n5", "tool", { name: "query_stock_prices", after: ["n3"], output: { ok: true, count: 0 } }),
  node("n6", "tool", { name: "query_latest_forecast", after: ["n3"], status: "failed", output: { ok: false, error_code: "tool_timeout" } }),
  node("n7", "verify", { output: { citations: 2, issues: [] } }),
  node("n8", "output", { output: { status: "succeeded", citations: 2 } }),
]);

test("the question and the answer are not chips; every other node of the trace is", () => {
  assert.deepEqual(stepChips(TRACE).map((chip) => chip.kind), ["classify", "decide", "tool", "tool", "tool", "verify"]);
});

test("a tool that found something shows its count, one that found nothing says so, one that failed says why", () => {
  const [, , found, none, failed] = stepChips(TRACE);
  assert.deepEqual([found.outcome, found.count], ["count", 3]);
  assert.deepEqual([none.outcome, none.count], ["none", null]);
  assert.deepEqual([failed.outcome, failed.reason, failed.reasonKnown, failed.state], ["failed", "工具超时", true, "failed"]);
});

test("a tool still running says nothing of a result, and a node with no data adds none", () => {
  const running = stepChips(normalizeTrace([node("a", "tool", { name: "query_sec_filings", status: "running", output: { ok: true, count: 3 } })]));
  assert.deepEqual([running[0].state, running[0].outcome, running[0].count], ["running", "", null]);
  const decide = stepChips(TRACE)[1];
  assert.equal(decide.outcome, "");
  assert.equal(decide.suffix, "#1");
});

test("the chip says what the existing title function says: the tool's Chinese name", () => {
  assert.equal(stepChips(TRACE)[2].label, "SEC 申报");
});

test("a running turn is the chips so far, the active step and the seconds since it started", () => {
  const running = normalizeTrace([node("a", "classify"), node("b", "decide", { step: 1, status: "running" })]);
  const model = barModel({ trace: running, running: true, startedAt: 1000, now: 4400 });
  assert.equal(model.kind, "running");
  assert.equal(model.chips.length, 2);
  assert.equal(model.seconds, "3.4");
  assert.equal(model.activeLabel, "模型决策");
  assert.equal(barModel({ running: true, startedAt: 1000, now: 1200 }).chips.length, 0);
});

test("a finished turn folds to the time the server kept and the step count of the old header", () => {
  const model = barModel({ trace: TRACE, thinkingMs: 12400, running: false });
  assert.deepEqual([model.kind, model.seconds, model.steps, model.chips.length], ["summary", "12", 6, 0]);
  assert.equal(barModel({ trace: TRACE, thinkingMs: 4400, running: false }).seconds, "4.4");
});

test("an old answer with no trace: only its time, or nothing", () => {
  assert.equal(barModel({ thinkingMs: 5100, running: false }).kind, "time");
  assert.equal(barModel({ thinkingMs: 5100, running: false }).seconds, "5.1");
  assert.equal(barModel({ running: false }).kind, "none");
  assert.equal(barModel({ trace: "garbage", running: false }).kind, "none");
});

test("the old tool badges keep their words", () => {
  const chips = legacyToolChips([
    { name: "query_latest_forecast", status: "complete", result: { count: 2 } },
    { name: "query_stock_prices", status: "complete", card: true, result: { data: [1, 2, 3] } },
    { name: "query_sec_filings", status: "not_found", result: { data: [] } },
    { name: "query_sec_filings", status: "failed", result: { error_code: "tool_timeout" } },
    { name: "query_sec_filings", status: "running" },
  ]);
  assert.deepEqual(chips.map((chip) => chip.status), ["已完成", "执行完成", "没有匹配记录", "查询失败", "执行中"]);
  assert.deepEqual(chips.map((chip) => chip.summary), ["", "3 条结果", "0 条结果", "tool_timeout", ""]);
  assert.equal(toolResultSummary({ job_status: "queued" }), "任务 queued");
  assert.deepEqual(legacyToolChips(undefined), []);
});
