import test from "node:test";
import assert from "node:assert/strict";
import { KERNEL_TOOLS, foldedLine, lookups, progressModel } from "../src/turn-progress.mjs";

const call = (name) => ({ name, status: "complete" });
const base = { narration: ["先看财报。", "再比价格。"], checklist: [{ text: "财报", status: "done" }, { text: "价格", status: "doing" }, { text: "结论", status: "pending" }], tier: "mid", toolTrace: [call("query_financials"), call("plan"), call("escalate"), call("query_stock_prices")], running: false };

test("an old-engine message and a kernel turn that answered directly have no model", () => {
  assert.equal(progressModel({}), null);
  assert.equal(progressModel({ narration: [], checklist: [], tier: undefined, toolTrace: [call("query_financials")], running: false }), null);
  assert.equal(progressModel({ narration: [], checklist: [], tier: "low", running: true }), null);
});

test("the kernel's own tools are not lookups", () => {
  assert.deepEqual(KERNEL_TOOLS, ["escalate", "plan"]);
  assert.deepEqual(lookups(base.toolTrace).map((x) => x.name), ["query_financials", "query_stock_prices"]);
  assert.equal(progressModel(base).lookupCount, 2);
});

test("while running the newest sentence is current; afterwards all are sentences", () => {
  const live = progressModel({ ...base, running: true });
  assert.equal(live.current, "再比价格。");
  assert.deepEqual(live.sentences, ["先看财报。"]);
  const done = progressModel(base);
  assert.equal(done.current, null);
  assert.deepEqual(done.sentences, ["先看财报。", "再比价格。"]);
});

test("a running turn without sentences yet has no current", () => {
  const live = progressModel({ ...base, narration: [], running: true });
  assert.equal(live.current, null);
  assert.deepEqual(live.sentences, []);
});

test("doneCount and items", () => {
  const m = progressModel(base);
  assert.equal(m.doneCount, 1);
  assert.equal(m.items.length, 3);
});

test("tierLabel", () => {
  assert.equal(progressModel({ ...base, tier: "mid" }).tierLabel, "中档");
  assert.equal(progressModel({ ...base, tier: "high" }).tierLabel, "高档");
  assert.equal(progressModel({ ...base, tier: "low" }).tierLabel, "");
  assert.equal(progressModel({ ...base, tier: "weird" }).tierLabel, "");
});

test("a tier above low alone is enough for a model", () => {
  const m = progressModel({ narration: [], checklist: [], tier: "high", running: false });
  assert.equal(m.tierLabel, "高档");
});

test("foldedLine keeps order and omits empty parts", () => {
  assert.deepEqual(foldedLine(progressModel(base), "12.4"), ["已思考 12.4 秒", "查了 2 次", "清单 1/3 项", "中档"]);
  const bare = progressModel({ narration: ["好。"], checklist: [], tier: "low", toolTrace: [], running: false });
  assert.deepEqual(foldedLine(bare, "3.0"), ["已思考 3.0 秒"]);
});

test("foldedLine passes each template through the translator", () => {
  const t = (s) => `<${s}>`;
  assert.deepEqual(foldedLine(progressModel(base), "1.0", t), ["<已思考 {n} 秒>".replace("{n}", "1.0"), "<查了 {n} 次>".replace("{n}", "2"), "<清单 {done}/{total} 项>".replace("{done}", "1").replace("{total}", "3"), "<中档>"]);
});

test("garbage input does not throw", () => {
  assert.doesNotThrow(() => progressModel({ narration: "x", checklist: 5, tier: 3, toolTrace: {}, running: true }));
  assert.equal(progressModel({ narration: "x", checklist: 5, tier: 3, toolTrace: {}, running: true }), null);
  const m = progressModel({ narration: [1, null, "ok"], checklist: [{ status: "done" }, null, { text: "a", status: "bogus" }, { text: "b" }], toolTrace: [null, {}, call("x")], running: false });
  assert.deepEqual(m.sentences, ["ok"]);
  assert.deepEqual(m.items.map((i) => i.text), ["a", "b"]);
  assert.deepEqual(m.items.map((i) => i.status), ["pending", "pending"]);
  assert.equal(m.lookupCount, 1);
  assert.equal(lookups(undefined).length, 0);
  assert.equal(foldedLine(null, "1.0").length, 0);
});
