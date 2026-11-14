import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { STARTER_PHRASES, botSymbol, starterQuestions } from "../src/starter-questions.mjs";

const bot = (fields) => ({ template: "blank", focus: { companies: [], theme: null }, default_company: null, ...fields });

test("a bot with a company gets that company's quote, latest filing and latest forecast", () => {
  const list = starterQuestions(bot({ focus: { companies: [{ symbol: "aapl" }] } }));
  assert.deepEqual(list.map((item) => item.text), ["查看 AAPL 最近行情", "AAPL 已保存的最新财报有哪些", "AAPL 最新的预测是什么"]);
  assert.ok(list.every((item) => item.symbol === "AAPL" && item.phrase.includes("{symbol}")));
});

test("the default company counts when the bot watches none; a watched one wins over it", () => {
  assert.equal(botSymbol(bot({ default_company: { symbol: "TSLA", company: "Tesla" } })), "TSLA");
  assert.equal(botSymbol(bot({ focus: { companies: [{ symbol: "NVDA" }] }, default_company: { symbol: "TSLA" } })), "NVDA");
  assert.equal(botSymbol(bot({})), null);
  assert.equal(botSymbol(null), null);
  assert.equal(botSymbol(bot({ focus: { companies: [{ symbol: "  " }] } })), null);
});

test("the news and earnings templates get today's news and the latest earnings read", () => {
  assert.ok(starterQuestions(bot({ template: "news_monitor" }))[0].text.includes("要闻"));
  assert.ok(starterQuestions(bot({ template: "earnings_reader" }))[0].text.includes("财报"));
  assert.ok(starterQuestions(bot({ template: "news_monitor" })).every((item) => item.symbol === null));
});

test("a company researcher with no company filled in (TeslaBot as it is) and any other bot get questions that name no company", () => {
  for (const given of [bot({ template: "company_researcher" }), bot({ template: "blank" }), null]) {
    const list = starterQuestions(given);
    assert.equal(list.length, 3);
    assert.ok(list.every((item) => item.symbol === null && !item.text.includes("{symbol}")));
  }
});

test("every phrase is in the English catalog", async () => {
  const english = JSON.parse(await readFile(new URL("../src/locales/en-US.json", import.meta.url), "utf8"));
  assert.deepEqual(STARTER_PHRASES.filter((phrase) => !(phrase in english)), []);
});
