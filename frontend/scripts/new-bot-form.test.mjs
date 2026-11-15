import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { PREVIEW_BOT_ID, createFields, createName, previewBot } from "../src/new-bot-form.mjs";
import { archetypeOf, derivePersona } from "../src/bot-persona.mjs";
import { BOT_TEMPLATES } from "../tools/shots/fixtures/bots.mjs";

const baseline = JSON.parse(await readFile(new URL("../tools/shots/fixtures/new-bot-bodies-baseline.json", import.meta.url), "utf8"));
const { templates, tools } = BOT_TEMPLATES;
const template = id => templates.find(x => x.id === id);
const LOOK = { shape: "triangle", color: "creme" };

// The inputs of the baseline scenarios (recorded on the old dialog in P5.2, tools/shots/fixtures/new-bot-bodies-baseline.json).
const INPUTS = {
  "name-only": ["读财报二号", null], "template-news-with-name": ["盯新闻", "news_monitor"], "template-company-with-name": ["公司二号", "company_researcher"],
  "template-earnings-no-name": ["", "earnings_reader"], "template-picked-then-off": ["取消了模板", null], "look-shape-color": ["换了外形", null],
  "name-trimmed": ["  有空格  ", null], "duplicate-name": ["AppleBot", null],
};

test("a create sends, for the same input, the old dialog's body field by field (the look aside, which was random)", () => {
  for (const [scenario, [name, id]] of Object.entries(INPUTS)) {
    const [sent] = baseline[scenario].bodies;
    const look = scenario === "look-shape-color" ? { shape: "nuage", color: "bleu" } : LOOK;
    assert.deepEqual(createFields(name, id ? template(id) : null, tools, look), sent, scenario);
  }
});

test("only a name is needed: nothing else is sent but the template mark, the robot avatar and the look", () => {
  const body = createFields("新助理", null, tools, LOOK);
  assert.deepEqual(Object.keys(body), ["name", "template", "avatar", "look"]);
  assert.equal(body.template, "blank");
  assert.equal(createName("   ", null, tools), "", "a blank name does not create");
});

test("a template names the bot when the name was left blank, and never overwrites a typed name", () => {
  assert.equal(createName("", template("news_monitor"), tools), "NewsBot");
  assert.equal(createName(" 我的 ", template("news_monitor"), tools), "我的");
});

test("the preview's stand-in bot gets the personality its template gives, and a typed name can not change it", () => {
  const want = { news_monitor: "sentinel", earnings_reader: "reader", company_researcher: "tracker" };
  for (const [id, archetype] of Object.entries(want)) assert.equal(archetypeOf(previewBot(template(id))), archetype, id);
  assert.equal(archetypeOf(previewBot(null)), "generalist");
  assert.equal(archetypeOf(previewBot(template("blank"))), "generalist");
  assert.equal(previewBot(null).id, PREVIEW_BOT_ID);
  assert.deepEqual(derivePersona(previewBot(null)), derivePersona(previewBot(null)), "the same every time");
  assert.notEqual(derivePersona(previewBot(template("news_monitor"))).archetype, derivePersona(previewBot(null)).archetype);
});
