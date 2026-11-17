import assert from "node:assert/strict";
import test from "node:test";
import { MONITOR_HEALTHS, monitorDot, monitorState, runMoments, staleHours, symbolRows } from "../src/app/research/monitor/monitor-model.mjs";

test("the four health states each have a fixed kind: success, action, failure, neutral", () => {
  assert.deepEqual(MONITOR_HEALTHS.map((h) => monitorState(h).kind), ["success", "action", "failure", "neutral"]);
  assert.deepEqual(MONITOR_HEALTHS.map((h) => monitorState(h).phrase), ["监控正常", "监控延迟", "监控异常", "尚无记录"]);
  assert.deepEqual(MONITOR_HEALTHS.map((h) => monitorState(h).headline), ["最近扫描成功", "运行延迟", "部分失败或降级", "没有运行记录"]);
  assert.equal(monitorState("anything-new").id, "not_recorded");
});

test("only a late or failing monitor puts a dot beside 研究", () => {
  assert.deepEqual(["healthy", "delayed", "degraded", "not_recorded", null, undefined, "x"].map(monitorDot), [null, "action", "failure", null, null, null, null]);
  assert.deepEqual(MONITOR_HEALTHS.map((h) => monitorState(h).dot), [null, "action", "failure", null]);
});

const run = (extra = {}) => ({ id: "r1", status: "succeeded", started_at: "2026-11-13T01:00:00Z", completed_at: "2026-11-13T01:04:00Z", next_due_at: "2026-11-13T02:00:00Z", per_symbol_results: {}, error_summary: null, retry_reason: null, ...extra });

test("the timeline is the last run and, when it is another run, the last full success", () => {
  assert.deepEqual(runMoments(null), []);
  assert.deepEqual(runMoments({ last_run: null, last_success: null }), []);
  const same = runMoments({ last_run: run(), last_success: { id: "r1", completed_at: "2026-11-13T01:04:00Z" } });
  assert.deepEqual(same.map((m) => [m.id, m.alsoLastSuccess]), [["last-run", true]]);
  const other = runMoments({ last_run: run({ status: "partial" }), last_success: { id: "r0", completed_at: "2026-11-12T01:04:00Z" } });
  assert.deepEqual(other.map((m) => [m.id, m.status, m.completedAt]), [["last-run", "partial", "2026-11-13T01:04:00Z"], ["last-success", "succeeded", "2026-11-12T01:04:00Z"]]);
});

test("the per-company rows put failures first, then partial scans, and keep the server's order inside a group", () => {
  const rows = symbolRows(run({ per_symbol_results: {
    AAPL: { status: "succeeded", discovered_count: 2, created_count: 1, queued_count: 0 },
    TSLA: { status: "failed", error: "sec_fetch_failed" },
    NVDA: { status: "succeeded" },
    AMD: { status: "incomplete", discovered_count: 3 },
  } }));
  assert.deepEqual(rows.map((r) => r.ticker), ["TSLA", "AMD", "AAPL", "NVDA"]);
  assert.deepEqual(rows[0], { ticker: "TSLA", status: "failed", error: "sec_fetch_failed", discovered: 0, created: 0, queued: 0 });
  assert.deepEqual(rows[2], { ticker: "AAPL", status: "succeeded", error: null, discovered: 2, created: 1, queued: 0 });
  assert.deepEqual(symbolRows(null), []);
});

test("the late threshold is shown in whole hours", () => {
  assert.equal(staleHours(7200), 2);
  assert.equal(staleHours(5400), 2);
  assert.equal(staleHours(undefined), 0);
});
