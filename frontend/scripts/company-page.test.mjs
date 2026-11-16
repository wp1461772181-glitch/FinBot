import assert from "node:assert/strict";
import test from "node:test";
import { askBots, askDraft, companyIsEmpty, companyName, prepareAsk } from "../src/company-page.mjs";
import { loadDraft, saveDraft } from "../src/chat-lines.mjs";
import { symbolKey } from "../src/workspace-cards.mjs";

const memory = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };
const bot = (id, fields = {}) => ({ id, name: id, hidden: false, is_default: false, focus: { companies: [], theme: null }, default_company: null, ...fields });
const BOTS = [
  bot("fin", { is_default: true }),
  bot("apple", { focus: { companies: [{ symbol: "AAPL", name: null }] }, default_company: { symbol: "AAPL", company: "Apple Inc." } }),
  bot("tesla"),
  bot("quiet", { hidden: true, focus: { companies: [{ symbol: "NVDA", name: "NVIDIA Corporation" }] } }),
];

test("the 问 bot menu lists the bots that follow the company; with none, only the default bot", () => {
  assert.deepEqual(askBots("AAPL", BOTS).bots.map((b) => b.id), ["apple"]);
  assert.equal(askBots("AAPL", BOTS).following, true);
  const tsla = askBots("TSLA", BOTS);
  assert.deepEqual(tsla.bots.map((b) => b.id), ["fin"]);
  assert.equal(tsla.following, false);
  // A hidden bot is not offered (the sidebar does not list it either); the company falls back to the default bot.
  assert.deepEqual(askBots("NVDA", BOTS).bots.map((b) => b.id), ["fin"]);
  assert.deepEqual(askBots("AAPL", []).bots, []);
});

test("the company's name comes from a bot that knows it, else the table, else nothing", () => {
  assert.equal(companyName("AAPL", BOTS), "Apple Inc.");
  assert.equal(companyName("NVDA", BOTS), "NVIDIA Corporation");
  assert.equal(companyName("TSLA", BOTS), "Tesla");
  assert.equal(companyName("ZZZZ", BOTS), null);
  assert.equal(companyName("TSLA"), "Tesla");
});

test("asking a bot makes the company its current stock and fills an empty draft, once", () => {
  const storage = memory();
  const first = prepareAsk({ bot: BOTS[1], symbol: "AAPL", draftText: askDraft("AAPL"), storage });
  assert.deepEqual(first, { prefilled: true, line: "bot:apple" });
  assert.equal(storage.getItem(symbolKey("apple")), "AAPL");
  assert.equal(loadDraft("bot:apple", storage), "关于 AAPL：");
});

test("a draft the reader already typed is never overwritten", () => {
  const storage = memory();
  saveDraft("bot:fin", "我在写的问题", storage);
  const result = prepareAsk({ bot: BOTS[0], symbol: "TSLA", draftText: askDraft("TSLA"), storage });
  assert.equal(result.prefilled, false);
  assert.equal(loadDraft("bot:fin", storage), "我在写的问题");
  assert.equal(storage.getItem(symbolKey("fin")), "TSLA");
});

test("the draft starts with the word 关于 and the company, in either language", () => {
  assert.equal(askDraft("TSLA"), "关于 TSLA：");
  assert.equal(askDraft("TSLA", { about: "About", colon: ": " }), "About TSLA: ");
});

test("a company is empty only when every read came back and held nothing", () => {
  assert.equal(companyIsEmpty({ prices: 0, forecasts: 0, materials: 0, filings: 0 }), true);
  assert.equal(companyIsEmpty({ prices: 0, forecasts: 0, materials: 0, filings: 1 }), false);
  assert.equal(companyIsEmpty({ prices: null, forecasts: 0, materials: 0, filings: 0 }), false);
  assert.equal(companyIsEmpty({ prices: 0, forecasts: Number.NaN, materials: 0, filings: 0 }), false);
});
