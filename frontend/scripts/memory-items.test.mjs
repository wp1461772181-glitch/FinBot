import assert from "node:assert/strict";
import test from "node:test";
import { originLabel, profileGroups, recallKindLabel } from "../src/memory-items.mjs";

const item = (id, origin, status, created_at) => ({ id, origin, status, created_at, kind: "preference", text: id, quote: id });

test("active items come first, explicit before inferred, oldest first within each; archived apart", () => {
  const groups = profileGroups([
    item("b", "inferred", "active", "2026-10-02"), item("old", "explicit", "archived", "2026-09-01"),
    item("c", "explicit", "active", "2026-10-03"), item("a", "explicit", "active", "2026-10-01"),
  ]);
  assert.deepEqual(groups.active.map(i => i.id), ["a", "c", "b"]);
  assert.deepEqual(groups.archived.map(i => i.id), ["old"]);
});

test("badges name where an item came from and what a recall line is", () => {
  assert.equal(originLabel("explicit"), "你说的");
  assert.equal(originLabel("inferred"), "推断");
  assert.equal(recallKindLabel("summary"), "摘要");
  assert.equal(recallKindLabel("questions"), "你的提问");
});

test("profile items are grouped 全局 first, then each bot (default first), then deleted bots", async () => {
  const { profileLayers, layerLabel } = await import("../src/memory-items.mjs");
  const bots = [{ id: "apple", name: "苹果", is_default: false }, { id: "main", name: "助理", is_default: true }];
  const layers = profileLayers([
    { ...item("g", "explicit", "active", "2026-10-01"), bot_id: null },
    { ...item("a", "inferred", "active", "2026-10-02"), bot_id: "apple", bot_name: "苹果" },
    { ...item("x", "explicit", "active", "2026-10-03"), bot_id: "gone-bot", bot_name: null },
    { ...item("old", "explicit", "archived", "2026-09-01"), bot_id: "apple" },
  ], bots);
  assert.deepEqual(layers.map(l => [l.label, l.items.map(i => i.id)]),
    [["全局", ["g"]], ["助理", []], ["苹果", ["a"]], ["已删除的 bot", ["x"]]]);
  assert.equal(layerLabel({ bot_id: null }), "全局");
  assert.equal(layerLabel({ bot_id: "apple", bot_name: "苹果" }), "苹果");
});

test("past conversations are grouped by bot in the order they come", async () => {
  const { recallGroups } = await import("../src/memory-items.mjs");
  const groups = recallGroups([
    { conversation_id: "1", bot_id: "news", bot_name: "抓新闻" }, { conversation_id: "2", bot_id: "apple", bot_name: "苹果" },
    { conversation_id: "3", bot_id: "news", bot_name: "抓新闻" }, { conversation_id: "4", bot_id: null, bot_name: null },
  ]);
  assert.deepEqual(groups.map(g => [g.label, g.items.map(i => i.conversation_id)]),
    [["抓新闻", ["1", "3"]], ["苹果", ["2"]], ["未归属", ["4"]]]);
});

test("a typed item is checked before it is sent: text, kind and its layer (\"\" is 全局)", async () => {
  const { manualItemDraft, originLabel: label, profileGroups: groups } = await import("../src/memory-items.mjs");
  assert.deepEqual(manualItemDraft({ kind: "preference", text: "  金额都用  亿美元 ", layer: "" }),
    { fields: { kind: "preference", text: "金额都用 亿美元", bot_id: null } });
  assert.deepEqual(manualItemDraft({ kind: "instruction", text: "先讲服务业务", layer: "apple" }).fields.bot_id, "apple");
  assert.equal(manualItemDraft({ kind: "preference", text: "   " }).error, "先写下要记住的内容。");
  assert.equal(manualItemDraft({ kind: "preference", text: "x".repeat(201) }).error, "最多 200 个字。");
  assert.equal(manualItemDraft({ kind: "wish", text: "x" }).error, "请选择类型。");
  assert.equal(label("manual"), "你写的");
  // Typed items rank with the owner's own words, before inferred ones.
  const ordered = groups([item("i", "inferred", "active", "2026-10-01"), item("m", "manual", "active", "2026-10-02")]);
  assert.deepEqual(ordered.active.map(i => i.id), ["m", "i"]);
});

test("proposed guesses are their own group, never active and never archived; a confirmed one is labelled", async () => {
  const { proposedItems, originLabel: label } = await import("../src/memory-items.mjs");
  const list = [
    { ...item("p-old", "pattern", "proposed", "2026-11-01"), examples: [{ message_id: "m1", quote: "q", date: "2026-10-30" }] },
    { ...item("p-new", "pattern", "proposed", "2026-11-20") },
    item("mine", "explicit", "active", "2026-10-01"), { ...item("kept", "pattern", "active", "2026-10-02") },
    item("old", "explicit", "archived", "2026-09-01"),
  ];
  const groups = profileGroups(list);
  assert.deepEqual(proposedItems(list).map(i => i.id), ["p-new", "p-old"]);
  assert.deepEqual(groups.active.map(i => i.id), ["mine", "kept"]);
  assert.deepEqual(groups.archived.map(i => i.id), ["old"]);
  assert.equal(label("pattern"), "你确认的推测");
  assert.deepEqual(proposedItems(null), []);
});

test("examples are shown with a short date; bad rows are dropped", async () => {
  const { exampleLines } = await import("../src/memory-items.mjs");
  assert.deepEqual(exampleLines({ examples: [{ message_id: "a", quote: " 先说结论 ", date: "2026-11-03T08:00:00+00:00" }, { quote: "" }, null] }),
    [{ key: "a", quote: "先说结论", date: "2026-11-03" }]);
  assert.deepEqual(exampleLines({ examples: null }), []);
});
