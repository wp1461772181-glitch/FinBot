import test from "node:test";
import assert from "node:assert/strict";
import { PART_KEYS, barSegments, compactLabel, formatKb, formatTokens, meterTone, noticesAfter, normalizeCompactions, normalizeContextUsage, parseCompactCommand } from "../src/context-usage.mjs";

const server = {
  budget_kb: 64, budget_bytes: 65536, capacity_bytes: 72000, used_bytes: 30000, remaining_bytes: 42000, remaining_percent: 58,
  compressing: true, hidden_turns: 2,
  parts: [
    { key: "system", bytes: 2200, tokens: 550 }, { key: "tools", bytes: 4600, tokens: 1150 },
    { key: "summary", bytes: 1200, tokens: 300, segments: 2 }, { key: "compressed", bytes: 6000, tokens: 1500, turns: 9 },
    { key: "recent", bytes: 16000, tokens: 4000, turns: 3 }, { key: "free", bytes: 42000, tokens: 10500 },
  ],
};

test("the server's report becomes the card's numbers, parts in a fixed order", () => {
  const usage = normalizeContextUsage({ ...server, parts: [...server.parts].reverse() });
  assert.deepEqual(usage.parts.map(part => part.key), PART_KEYS);
  assert.equal(usage.remainingPercent, 58);
  assert.equal(usage.parts.find(part => part.key === "summary").segments, 2);
  assert.equal(usage.parts.find(part => part.key === "compressed").turns, 9);
  assert.equal(usage.compressing, true);
  assert.equal(usage.hiddenTurns, 2);
});

test("anything unusable is refused, odd values are clamped", () => {
  assert.equal(normalizeContextUsage(null), null);
  assert.equal(normalizeContextUsage("x"), null);
  assert.equal(normalizeContextUsage({ ...server, parts: [] }), null);
  assert.equal(normalizeContextUsage({ ...server, capacity_bytes: 0 }), null);
  const odd = normalizeContextUsage({ ...server, remaining_percent: 180, used_bytes: 10 ** 9,
    parts: [{ key: "recent", bytes: -5, tokens: "a" }, { key: "recent", bytes: 99 }, { key: "bogus", bytes: 1 }] });
  assert.equal(odd.remainingPercent, 100);
  assert.equal(odd.usedBytes, odd.capacityBytes);
  assert.deepEqual(odd.parts, [{ key: "recent", bytes: 0, tokens: 0 }]);
});

test("sizes are written in KB and tokens in k", () => {
  assert.equal(formatKb(0), "0.0 KB");
  assert.equal(formatKb(2200), "2.1 KB");
  assert.equal(formatKb(65536), "64.0 KB");
  assert.equal(formatKb(130 * 1024), "130 KB");
  assert.equal(formatTokens(550), "550");
  assert.equal(formatTokens(10500), "10.5k");
});

test("the bar covers the capacity and leaves out empty parts", () => {
  const usage = normalizeContextUsage(server);
  const bar = barSegments(usage);
  assert.deepEqual(bar.map(item => item.key), PART_KEYS);
  assert.ok(Math.abs(bar.reduce((sum, item) => sum + item.percent, 0) - 100) < 1.5);
  const empty = normalizeContextUsage({ ...server, parts: [{ key: "system", bytes: 100, tokens: 25 }, { key: "free", bytes: 200, tokens: 50 }] });
  assert.deepEqual(barSegments(empty).map(item => item.key), ["system", "free"]);
  assert.deepEqual(barSegments(null), []);
});

test("the pill warns as the budget runs out", () => {
  const at = percent => normalizeContextUsage({ ...server, remaining_percent: percent });
  assert.equal(meterTone(at(80)), "ok");
  assert.equal(meterTone(at(30)), "warn");
  assert.equal(meterTone(at(10)), "full");
  assert.equal(meterTone(null), "ok");
});

test("the pill follows the share of the history budget used, and the line where compression starts", () => {
  const at = percent => normalizeContextUsage({ ...server, history_used_percent: percent, compact_at_percent: 80, will_compact: percent >= 80 });
  assert.equal(at(40).usedPercent, 40);
  assert.equal(at(40).compactAtPercent, 80);
  assert.equal(meterTone(at(40)), "ok");
  assert.equal(meterTone(at(79)), "ok");
  assert.equal(meterTone(at(80)), "warn");     // compression starts on its own here
  assert.equal(meterTone(at(97)), "full");
  assert.equal(at(85).willCompact, true);
  // an old server without the new fields keeps the earlier reading
  const old = normalizeContextUsage({ ...server, remaining_percent: 20 });
  assert.equal(old.usedPercent, 80);
  assert.equal(meterTone(old), "warn");
});

test("a budget bigger than the old 128 KB ceiling is shown as it is", () => {
  const big = normalizeContextUsage({ ...server, budget_kb: 187, budget_bytes: 192000 });
  assert.equal(big.budgetKb, 187);
  assert.equal(formatKb(192000), "188 KB");
});

test("the compress command is recognised whole-message only, with its focus", () => {
  assert.deepEqual(parseCompactCommand("/压缩"), { compact: true, focus: "" });
  assert.deepEqual(parseCompactCommand("  /压缩 重点保留 Intel 的分析 "), { compact: true, focus: "重点保留 Intel 的分析" });
  assert.deepEqual(parseCompactCommand("/compact keep Intel"), { compact: true, focus: "keep Intel" });
  assert.equal(parseCompactCommand("/压缩了吗").compact, false);
  assert.equal(parseCompactCommand("请 /压缩").compact, false);
  assert.equal(parseCompactCommand(undefined).compact, false);
  assert.equal(parseCompactCommand("/压缩 " + "长".repeat(500)).focus.length, 200);
});

test("compaction notices say how many turns were compressed and carry the summary to open", () => {
  const notices = normalizeCompactions([
    { id: 2, after_turn_id: "t9", turns: 12, total: 40, focus: "Intel", summary: "目标: 看 Intel", created_at: "2026-11-03T10:00:00Z" },
    { id: 1, after_turn_id: "t3", turns: 5, total: 5, summary: "x" },
    { id: 3, turns: 2 }, { id: "bad" }, null, { id: 1, after_turn_id: "t3", turns: 5 },
  ]);
  assert.deepEqual(notices.map(n => n.id), [1, 2]);                      // unusable and repeated ones dropped, oldest first
  assert.equal(compactLabel(12), "已压缩 12 轮");
  assert.deepEqual(noticesAfter(notices, "t9").map(n => n.label), ["已压缩 12 轮"]);
  assert.equal(noticesAfter(notices, "t9")[0].summary, "目标: 看 Intel");
  assert.equal(noticesAfter(notices, "t9")[0].focus, "Intel");
  assert.deepEqual(noticesAfter(notices, "nope"), []);
  assert.deepEqual(noticesAfter(notices, undefined), []);
});
