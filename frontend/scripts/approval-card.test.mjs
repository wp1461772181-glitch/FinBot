import test from "node:test";
import assert from "node:assert/strict";
import { APPROVAL_TTL_MS, answerSummary, approvalKind, arrangeChoices, formatRemaining, isExpired, pickState, remainingMs, targetRows } from "../src/approval-card.mjs";

const write = { reason: "write_confirmation", display: { title: "抓取并分析 NVDA 10-Q", targets: [{ symbol: "NVDA", form: "10-Q", source_id: "x1", record_id: "r1" }] },
  choices: [{ label: "确认执行", value: "confirm:fetch_analyze" }, { label: "先不要", value: "cancel" }] };
const revision = { reason: "choose_revision_sources", options: [{ value: "1", label: "a" }, { value: "2", label: "b" }, { value: "3", label: "c" }], select: { min: 2, max: 3 },
  choices: [{ label: "用所选材料修订", value: "confirm:revise_forecast" }, { label: "先不要", value: "cancel:revise_forecast" }] };
const question = { reason: "reference_item_unavailable", choices: [{ label: "第一条结果", value: "a" }, { label: "第二条结果", value: "b" }, { label: "第三条结果", value: "c" }] };

test("three kinds of card", () => {
  assert.equal(approvalKind(write), "write");
  assert.equal(approvalKind(revision), "revision");
  assert.equal(approvalKind(question), "question");
  assert.equal(approvalKind({ reason: "choose_write_action", choices: [] }), "write");
});

test("a confirm card has two main buttons: the first choice and the one that cancels; the rest wait in the menu", () => {
  const two = arrangeChoices(write);
  assert.deepEqual([two.layout, two.primary.value, two.secondary.value, two.more], ["confirm", "confirm:fetch_analyze", "cancel", []]);
  const many = arrangeChoices({ reason: "confirm_write", choices: [{ label: "A", value: "confirm:a" }, { label: "B", value: "confirm:b" }, { label: "不要", value: "cancel" }, { label: "C", value: "later" }] });
  assert.deepEqual([many.primary.value, many.secondary.value, many.more.map((c) => c.value)], ["confirm:a", "cancel", ["confirm:b", "later"]]);
  const noCancel = arrangeChoices({ reason: "confirm_write", choices: [{ label: "A", value: "confirm:a" }, { label: "B", value: "confirm:b" }, { label: "C", value: "confirm:c" }] });
  assert.deepEqual([noCancel.secondary.value, noCancel.more.map((c) => c.value)], ["confirm:c", ["confirm:b"]]);
  assert.equal(arrangeChoices({ reason: "confirm_write", choices: [{ label: "A", value: "confirm:a" }] }).secondary, null);
});

test("a question card lists its choices as options and has no main button", () => {
  const list = arrangeChoices(question);
  assert.deepEqual([list.layout, list.primary, list.secondary, list.list.length], ["list", null, null, 3]);
});

test("ten minutes, counted down to the second and rounded up", () => {
  assert.equal(APPROVAL_TTL_MS, 600000);
  assert.equal(remainingMs(1000, 1000), 600000);
  assert.equal(remainingMs(1000, 1000 + 599500), 500);
  assert.equal(remainingMs(1000, 1000 + 700000), 0);
  assert.equal(formatRemaining(600000), "10:00");
  assert.equal(formatRemaining(500), "00:01");
  assert.equal(formatRemaining(61000), "01:01");
  assert.equal(formatRemaining(0), "00:00");
  assert.equal(isExpired(0, 599999), false);
  assert.equal(isExpired(0, 600000), true);
});

test("a revision card wants its minimum ticked; without any candidate it says so", () => {
  assert.deepEqual(pickState(revision, 0), { min: 2, max: 3, picked: 0, missing: 2, noCandidates: false });
  assert.equal(pickState(revision, 1).missing, 1);
  assert.equal(pickState(revision, 2).missing, 0);
  const none = { reason: "choose_revision_sources", choices: [{ label: "先不要", value: "cancel" }] };
  assert.equal(pickState(none, 0).noCandidates, true);
  assert.equal(pickState(none, 0).missing, 0);
  assert.equal(pickState(write, 0).noCandidates, false);
});

test("targets show their field names in words and never an id", () => {
  const rows = targetRows(write.display);
  assert.deepEqual(rows, [[{ key: "symbol", label: "公司代码", known: true, value: "NVDA" }, { key: "form", label: "表单类型", known: true, value: "10-Q" }]]);
  assert.deepEqual(targetRows({ targets: [{ source_id: "only-an-id" }, { extra_field: 3 }] }), [[{ key: "extra_field", label: "extra_field", known: false, value: "3" }]]);
  assert.deepEqual(targetRows(undefined), []);
});

test("what a finished card says of itself", () => {
  assert.deepEqual(answerSummary(write, "确认执行"), { outcome: "confirmed", detail: "抓取并分析 NVDA 10-Q" });
  assert.deepEqual(answerSummary(write, "先不要"), { outcome: "cancelled", detail: "抓取并分析 NVDA 10-Q" });
  // A line typed in the composer instead of pressing a button: the write was never confirmed.
  assert.deepEqual(answerSummary(write, "我再想想"), { outcome: "skipped", detail: "抓取并分析 NVDA 10-Q" });
  assert.equal(answerSummary(revision, "[hand-fed] 过程条").outcome, "skipped");
  assert.deepEqual(answerSummary(revision, "用所选的 2 份材料修订"), { outcome: "confirmed", detail: "用所选的 2 份材料修订" });
  assert.equal(answerSummary(revision, "先不要").outcome, "cancelled");
  assert.deepEqual(answerSummary(question, "第二条结果"), { outcome: "answered", detail: "第二条结果" });
});
