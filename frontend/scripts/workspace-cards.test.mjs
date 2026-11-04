import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_LAYOUT, addCard, botSymbol, cleanLayout, forecastCardModel, loadLayout, moveCard, pinCardSymbol, priceSummary, removeCard, resetLayout, saveLayout, storeBotSymbol, symbolChoices } from "../src/workspace-cards.mjs";

const memory = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };

test("six default cards (with 我的持仓); edit, save, reload and reset per bot", () => {
  const s = memory();
  assert.deepEqual(loadLayout("b1", s).map((x) => x.card), ["price", "forecast", "materials", "filings", "routines", "portfolio"]);
  let layout = loadLayout("b1", s);
  layout = removeCard(layout, layout.findIndex((x) => x.card === "filings"));
  layout = addCard(layout, "brief");
  layout = moveCard(layout, layout.length - 1, -1);
  layout = pinCardSymbol(layout, 0, "nvda");
  saveLayout("b1", layout, s);
  const again = loadLayout("b1", s);
  assert.deepEqual(again.map((x) => x.card), ["price", "forecast", "materials", "routines", "brief", "portfolio"]);
  assert.equal(again[0].symbol, "NVDA");
  assert.equal(loadLayout("b2", s).length, DEFAULT_LAYOUT.length);
  assert.equal(resetLayout("b1", s).length, 6);
  assert.equal(loadLayout("b1", s)[3].card, "filings");
});

test("a saved 待你确认 card becomes the one 例行任务 card", () => {
  assert.deepEqual(cleanLayout([{ card: "price" }, { card: "confirm", size: "m" }]), [{ card: "price" }, { card: "routines", size: "m" }]);
  assert.deepEqual(cleanLayout([{ card: "confirm" }, { card: "routines" }]), [{ card: "routines" }]);
});

test("a stored layout is cleaned: unknown cards and bad symbols dropped", () => {
  assert.deepEqual(cleanLayout([{ card: "price", symbol: "<x>" }, { card: "nope" }, { card: "brief", size: "l" }]), [{ card: "price" }, { card: "brief", size: "l" }]);
  assert.equal(cleanLayout("x"), null);
  assert.deepEqual(moveCard([{ card: "price" }], 0, -1), [{ card: "price" }]);
});

test("current stock is per bot: picked › default company › first focus › page", () => {
  const s = memory();
  const apple = { id: "apple", focus: { companies: [{ symbol: "AAPL" }] } };
  assert.equal(botSymbol(apple, "TSLA", s), "AAPL");
  assert.equal(botSymbol({ id: "any", focus: { companies: [] } }, "TSLA", s), "TSLA");
  storeBotSymbol("apple", "msft", s);
  assert.equal(botSymbol(apple, "TSLA", s), "MSFT");
  assert.equal(storeBotSymbol("apple", "bad symbol", s), null);
  assert.deepEqual(symbolChoices(apple, ["NVDA", "AAPL"], "MSFT"), ["MSFT", "AAPL", "NVDA"]);
});

test("the 研究预测 card shows the newest forecast of the stock: model, target date, probabilities, link to its page", () => {
  const rows = [
    { id: "r-old", symbol: "AMD", latest_version_no: 1, decision_at: "2026-10-01T00:00:00Z", target_end_date: "2026-10-29", model_status: "experimental_llm",
      decider: { actual_model: "model-old" }, probabilities: { bearish: 0.5, neutral: 0.3, bullish: 0.2 } },
    { id: "r-new", symbol: "AMD", latest_version_no: 3, decision_at: "2026-11-02T00:00:00Z", target_end_date: "2026-12-01", model_status: "experimental_llm",
      decider: { actual_model: "model-new" }, probabilities: { bearish: 0.2, neutral: 0.3, bullish: 0.5 } },
    { id: "r-other", symbol: "NVDA", latest_version_no: 1, decision_at: "2026-11-03T00:00:00Z", target_end_date: "2026-12-02", model_status: "experimental_llm", decider: {}, probabilities: null },
  ];
  const card = forecastCardModel(rows, "amd");
  assert.equal(card.hash, "#forecast/r-new");
  assert.equal(card.model, "model-new");
  assert.equal(card.targetDate, "2026-12-01");
  assert.deepEqual(card.percent, { bearish: 20, neutral: 30, bullish: 50 });
  assert.equal(card.decisionAt, "2026-11-02T00:00:00Z");
  assert.equal(forecastCardModel(rows, "TSLA"), null);
  assert.equal(forecastCardModel(undefined, "AMD"), null);
  const bare = forecastCardModel(rows, "NVDA");
  assert.equal(bare.model, null);
  assert.equal(bare.percent, null);
});

test("price summary is facts only", () => {
  assert.equal(priceSummary([]), null);
  const p = priceSummary([{ trading_date: "2026-10-26", close: 100 }, { trading_date: "2026-10-27", close: 102 }]);
  assert.deepEqual(p, { date: "2026-10-27", close: 102, change: 2, pct: 2 });
});
