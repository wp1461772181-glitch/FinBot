import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { badgeKind, BADGE_KINDS, monitorChip, OPINION_DISCLAIMER, priceChange, recentCloses, signedChange, sparklinePoints, usableCandles } from "../src/data-display.mjs";

test("a signed change keeps the sign and gives the direction separately", () => {
  assert.deepEqual(signedChange(3.2, { digits: 2 }), { direction: "up", text: "+3.20" });
  assert.deepEqual(signedChange(-0.4, { digits: 2 }), { direction: "down", text: "−0.40" });
  assert.deepEqual(signedChange(0.001, { digits: 2 }), { direction: "flat", text: "0.00" });
  assert.deepEqual(signedChange(1.3, { digits: 2, suffix: "%" }), { direction: "up", text: "+1.30%" });
  assert.deepEqual(signedChange(Number.NaN), { direction: "flat", text: "—" });
});

const candle = (date, close) => ({ trading_date: date, open: close, high: close, low: close, close, volume: 1 });

test("price change is the last close against the one before it, as text with sign and percent", () => {
  const up = priceChange([candle("2026-11-10", 245.3), candle("2026-11-11", 248.5)]);
  assert.equal(up.close, 248.5);
  assert.equal(up.date, "2026-11-11");
  assert.equal(up.direction, "up");
  assert.equal(up.change, "+3.20");
  assert.equal(up.percent, "+1.30%");
  assert.equal(up.text, "+3.20 (+1.30%)");
  const down = priceChange([candle("a", 100), candle("b", 98.5)]);
  assert.equal(down.direction, "down");
  assert.equal(down.text, "−1.50 (−1.50%)");
});

test("one candle has a close but no change; none has nothing", () => {
  const single = priceChange([candle("a", 50)]);
  assert.equal(single.close, 50);
  assert.equal(single.text, "");
  assert.equal(single.direction, "flat");
  assert.equal(priceChange([]), null);
  assert.equal(priceChange(null), null);
});

test("the sparkline takes the last 63 closes, oldest first, and skips broken rows", () => {
  const rows = Array.from({ length: 100 }, (_, i) => candle(`d${i}`, i + 1));
  const closes = recentCloses(rows);
  assert.equal(closes.length, 63);
  assert.equal(closes[0], 38);
  assert.equal(closes.at(-1), 100);
  assert.deepEqual(recentCloses([candle("a", 1), { close: null }, candle("b", 2)]), [1, 2]);
  assert.deepEqual(recentCloses(undefined), []);
});

test("a badge is one of four tones or one of two materials; anything else is neutral", () => {
  assert.deepEqual(BADGE_KINDS, ["neutral", "progress", "success", "failure", "opinion", "action"]);
  assert.equal(badgeKind("success"), "success");
  assert.equal(badgeKind("opinion"), "opinion");
  assert.equal(badgeKind("red"), "neutral");
  assert.equal(badgeKind(undefined), "neutral");
});

test("the monitor chip maps the health to a kind and a phrase", () => {
  assert.deepEqual(monitorChip("healthy"), { kind: "success", phrase: "监控正常" });
  assert.deepEqual(monitorChip("degraded"), { kind: "failure", phrase: "监控异常" });
  assert.deepEqual(monitorChip("delayed"), { kind: "action", phrase: "监控延迟" });
  assert.deepEqual(monitorChip("not_recorded"), { kind: "neutral", phrase: "尚无记录" });
});

test("the sparkline fits the closes into the box, low at the bottom and high at the top", () => {
  assert.equal(sparklinePoints([1, 2, 3], 100, 20), "0,18 50,10 100,2");
  assert.equal(sparklinePoints([5, 5], 10, 20), "0,18 10,18");
  assert.equal(sparklinePoints([1], 100, 20), "");
  assert.equal(sparklinePoints(undefined, 100, 20), "");
  assert.equal(sparklinePoints([1, Number.NaN, 3], 100, 20), "0,18 100,2");
});

test("the chart only gets candles it can draw, oldest first", () => {
  const good = (d, c) => ({ trading_date: d, open: c, high: c + 1, low: c - 1, close: c, volume: 1 });
  const rows = [good("2026-11-03", 12), { ...good("2026-11-02", 10), high: 5 }, good("2026-11-01", 11), { ...good("2026-11-04", 0), open: 0 }, { trading_date: "", open: 1, high: 1, low: 1, close: 1 }];
  assert.deepEqual(usableCandles(rows).map((c) => c.trading_date), ["2026-11-01", "2026-11-03"]);
  assert.deepEqual(usableCandles(rows, 1).map((c) => c.trading_date), ["2026-11-03"]);
  assert.deepEqual(usableCandles(null), []);
});

test("the disclaimer sentence is the design's, word for word, and both languages have it", async () => {
  assert.equal(OPINION_DISCLAIMER, "概率未经校准，属实验性信息。仅供参考，买不买由你决定。");
  const zh = JSON.parse(await readFile(new URL("../src/locales/zh-CN.json", import.meta.url), "utf8"));
  const en = JSON.parse(await readFile(new URL("../src/locales/en-US.json", import.meta.url), "utf8"));
  assert.ok(zh.includes(OPINION_DISCLAIMER) && en[OPINION_DISCLAIMER]);
});

test("each of the four shared components has a data-slot on its root", async () => {
  const read = (name) => readFile(new URL(`../src/components/${name}.tsx`, import.meta.url), "utf8");
  assert.match(await read("OpinionCard"), /<section data-slot="opinion-card"/);
  assert.match(await read("ProbabilityBar"), /data-slot="probability-bar"/);
  assert.match(await read("StatTile"), /data-slot="stat-tile"/);
  assert.match(await read("StatusBadge"), /<span data-slot="status-badge"/);
});

test("the disclaimer is said once in each page area: one card of the company overview carries it, the watchlist has it once under its table", async () => {
  const overview = await readFile(new URL("../src/app/research/CompanyOverview.tsx", import.meta.url), "utf8");
  assert.equal((overview.match(/<OpinionCard [^>]*\bdisclaimer>/g) ?? []).length, 1);
  assert.equal((overview.match(/OPINION_DISCLAIMER/g) ?? []).length, 0);
  const watchlist = await readFile(new URL("../src/app/research/WatchlistPage.tsx", import.meta.url), "utf8");
  assert.equal((watchlist.match(/t\(OPINION_DISCLAIMER\)/g) ?? []).length, 1);
});
