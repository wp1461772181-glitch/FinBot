import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { SECTIONS, changedFields, draftOf, fieldsToSave, focusSymbols, groupTools, hasChanges, scopeSummary, sectionFromSearch, sectionsChanged, telegramStep, toolGroup, validate, withFocusSymbols, withFocusTheme } from "../src/bot-settings-form.mjs";
import { toggleTool } from "../src/bot-items.mjs";

// The server's bot, as the fake API holds AppleBot (tools/shots/fixtures/bots.mjs).
const bot = (extra = {}) => ({ id: "b3", name: "AppleBot", title: "资料助手", description: "只关注 Apple。", focus: { companies: [{ symbol: "AAPL", name: null }], theme: "服务业务" },
  tool_scope: null, model: null, reasoning_effort: null, avatar: "bot:bull-bull", look: { shape: "hexagone", color: "orange" }, group: "", pinned: true, hidden: false,
  daily_notify_cap: 5, template: "blank", is_default: false, ...extra });
const NAMES = ["get_market_data", "search_news", "read_filing", "create_forecast", "query_portfolio", "save_material"];

test("a draft that was not touched changes nothing and sends the old form's whole field set, no look and no effort", () => {
  const b = bot(), draft = draftOf(b);
  assert.deepEqual(changedFields(draft, b), []);
  assert.equal(hasChanges(draft, b), false);
  const body = fieldsToSave(draft, b);
  assert.deepEqual(Object.keys(body), ["name", "title", "description", "focus", "tool_scope", "model", "avatar", "group", "pinned", "hidden", "daily_notify_cap", "template"]);
  assert.deepEqual(body.focus.companies, [{ symbol: "AAPL", name: null }], "the server's records go back as they came");
});

test("every field of the old profile form is a change when edited, and belongs to the section that holds it", () => {
  const b = bot();
  const cases = [
    ["name", { name: "AppleBot 二号" }, "profile"], ["title", { title: "苹果研究员" }, "profile"], ["description", { description: "只看 Apple。" }, "profile"],
    ["group", { group: "公司" }, "profile"], ["pinned", { pinned: false }, "profile"], ["hidden", { hidden: true }, "profile"],
    ["focus", { focus: { ...b.focus, theme: "AI" } }, "focus"], ["avatar", { avatar: "🍎" }, "look"], ["look", { look: { shape: "nuage", color: "orange" } }, "look"],
    ["model", { model: "muse-ember" }, "model"], ["reasoning_effort", { reasoning_effort: "high" }, "model"], ["tool_scope", { tool_scope: ["search_news"] }, "tools"],
    ["daily_notify_cap", { daily_notify_cap: 9 }, "notify"],
  ];
  for (const [field, patch, section] of cases) {
    const draft = { ...draftOf(b), ...patch };
    assert.deepEqual(changedFields(draft, b), [field], field);
    assert.deepEqual([...sectionsChanged(draft, b)], [section], field);
  }
});

test("typing only spaces around a text is not a change; an emptied name is an error and not a save", () => {
  const b = bot();
  assert.equal(hasChanges({ ...draftOf(b), name: "  AppleBot ", group: "  " }, b), false);
  assert.deepEqual(validate({ ...draftOf(b), name: "  " }), { name: "名字不能为空。" });
  assert.deepEqual(validate(draftOf(b)), {});
});

test("a look picked and picked back is not sent (the server's look is the reference); a look on a bot that has none is", () => {
  const b = bot();
  assert.equal("look" in fieldsToSave({ ...draftOf(b), look: { shape: "hexagone", color: "orange" } }, b), false);
  assert.deepEqual(fieldsToSave({ ...draftOf(b), look: { shape: "nuage", color: "orange" } }, b).look, { shape: "nuage", color: "orange" });
  const none = bot({ look: null });
  assert.equal(hasChanges(draftOf(none), none), false);
  assert.equal(hasChanges({ ...draftOf(none), look: { shape: "cercle", color: "encre" } }, none), true);
  assert.equal("look" in fieldsToSave({ ...draftOf(b), look: { shape: "nope", color: "x" } }, b), false, "a look the catalog does not know is ignored");
});

test("the reasoning effort goes only when it was changed, and 默认 sends null", () => {
  const b = bot({ reasoning_effort: "high" });
  assert.equal("reasoning_effort" in fieldsToSave(draftOf(b), b), false);
  assert.equal(fieldsToSave({ ...draftOf(b), reasoning_effort: null }, b).reasoning_effort, null);
  assert.equal(fieldsToSave({ ...draftOf(b), reasoning_effort: "low" }, b).reasoning_effort, "low");
  const plain = bot();
  assert.equal(hasChanges({ ...draftOf(plain), reasoning_effort: null }, plain), false, "default stays default");
  assert.equal(hasChanges({ ...draftOf(plain), reasoning_effort: "high" }, plain), true);
  assert.equal(hasChanges({ ...draftOf(plain), reasoning_effort: "high" }, bot({ reasoning_effort: "high" })), false);
  const unset = bot({ reasoning_effort: undefined });
  assert.equal(hasChanges(draftOf(unset), unset), false, "a bot record without the field is the default");
});

test("the model goes back to the server's default as null", () => {
  const b = bot({ model: "haiku-5.5" });
  assert.equal(fieldsToSave({ ...draftOf(b), model: null }, b).model, null);
  assert.deepEqual(changedFields({ ...draftOf(b), model: null }, b), ["model"]);
});

test("the tool scope: all on is null (not a full list), one off is the rest, off and on again is no change", () => {
  const b = bot();
  const one = toggleTool(null, "create_forecast", NAMES);
  assert.deepEqual(one, NAMES.filter((n) => n !== "create_forecast"));
  assert.deepEqual(fieldsToSave({ ...draftOf(b), tool_scope: one }, b).tool_scope, one);
  assert.equal(toggleTool(one, "create_forecast", NAMES), null);
  assert.equal(hasChanges({ ...draftOf(b), tool_scope: toggleTool(one, "create_forecast", NAMES) }, b), false);
  const narrow = bot({ tool_scope: ["search_news"] });
  assert.deepEqual(changedFields({ ...draftOf(narrow), tool_scope: null }, narrow), ["tool_scope"], "全部打开 on a narrowed bot is a change to null");
  assert.equal(fieldsToSave({ ...draftOf(narrow), tool_scope: null }, narrow).tool_scope, null);
});

test("the focus companies: the same list keeps the server's records, a changed one is {symbol} for each (as the old text field re-parsed it)", () => {
  const b = bot(), draft = draftOf(b);
  assert.deepEqual(focusSymbols(draft), ["AAPL"]);
  assert.equal(withFocusSymbols(draft, ["AAPL"]), draft);
  const more = withFocusSymbols(draft, ["AAPL", "MSFT"]);
  assert.deepEqual(fieldsToSave(more, b).focus.companies, [{ symbol: "AAPL" }, { symbol: "MSFT" }]);
  assert.deepEqual(changedFields(more, b), ["focus"]);
  assert.deepEqual(fieldsToSave(withFocusSymbols(draft, []), b).focus.companies, []);
  assert.deepEqual(changedFields(withFocusSymbols(more, ["AAPL"]), b), [], "added and taken back: the server's list again, no change");
  assert.deepEqual(fieldsToSave(withFocusSymbols(more, ["AAPL"]), b).focus.companies, [{ symbol: "AAPL", name: null }], "and it goes out as the server's records");
  assert.deepEqual(changedFields(withFocusSymbols(draft, ["MSFT"]), b), ["focus"]);
  assert.equal(withFocusTheme(draft, "").focus.theme, null);
  assert.equal(fieldsToSave(withFocusTheme(draft, "  AI  "), b).focus.theme, "AI");
  assert.equal(fieldsToSave(withFocusTheme(draft, "   "), b).focus.theme, null);
});

test("the default bot's save still carries hidden and the cap, as it did", () => {
  const b = bot({ is_default: true, hidden: false });
  const body = fieldsToSave({ ...draftOf(b), name: "FinBot 主理" }, b);
  assert.equal(body.hidden, false);
  assert.equal(body.daily_notify_cap, 5);
});

test("the sections are nine, in the design's order, and only 技能 / 例行任务 are saved at once", () => {
  assert.deepEqual(SECTIONS.map((s) => s.id), ["profile", "focus", "look", "model", "tools", "skills", "routines", "notify", "danger"]);
  assert.deepEqual(SECTIONS.filter((s) => s.save === "live").map((s) => s.id), ["skills", "routines"]);
  assert.equal(sectionFromSearch("?section=tools"), "tools");
  assert.equal(sectionFromSearch("?section=nope"), "profile");
  assert.equal(sectionFromSearch(""), "profile");
  assert.equal(sectionFromSearch(undefined), "profile");
});

test("tools are grouped by their level; the two web tools are named; an unknown level lands in the last group", () => {
  const tools = [
    { name: "query_stock_prices", level: "read" }, { name: "web_research", level: "read" }, { name: "forecast", level: "costly" }, { name: "remember", level: "reversible" },
    { name: "ask_user", level: "card" }, { name: "notify_telegram", level: "notify" }, { name: "x", level: "mystery" }, { name: "search_configured_news", level: "read" },
  ];
  assert.equal(toolGroup(tools[0]), "read");
  const groups = groupTools(tools);
  assert.deepEqual(groups.map((g) => [g.id, g.tools.map((t) => t.name)]), [
    ["read", ["query_stock_prices"]], ["web", ["web_research", "search_configured_news"]], ["write", ["forecast", "remember"]], ["other", ["ask_user", "notify_telegram", "x"]] ]);
  assert.deepEqual(groupTools([{ name: "a", level: "read" }]).map((g) => g.id), ["read"], "empty groups are left out");
  assert.deepEqual(groupTools(undefined), []);
  assert.deepEqual(scopeSummary(null, 6), { all: true, count: 6, total: 6 });
  assert.deepEqual(scopeSummary(["a"], 6), { all: false, count: 1, total: 6 });
});

test("the Telegram binding is on one of four steps", () => {
  assert.equal(telegramStep(null, null), 0);
  assert.equal(telegramStep({ has_token: false, bound: false }, null), 0);
  assert.equal(telegramStep({ has_token: true, bound: false }, null), 1);
  assert.equal(telegramStep({ has_token: true, bound: false }, { code: "x" }), 2);
  assert.equal(telegramStep({ has_token: true, bound: true }, { code: "x" }), 3);
});

test("the page and the old form agree: the code of the page sends what the baseline of the old form sent", async () => {
  const baseline = JSON.parse(await readFile(new URL("../tools/shots/fixtures/bot-save-bodies-baseline.json", import.meta.url), "utf8"));
  const apple = { ...bot({ tool_scope: null }), description: "只关注 Apple：财报、新闻、预测与材料。", focus: { companies: [{ symbol: "AAPL", name: null }], theme: "所有相关资讯" }, look: { shape: "hexagone", color: "orange" } };
  const body = (draft) => JSON.parse(JSON.stringify(fieldsToSave(draft, apple)));
  const old = (name) => JSON.parse(baseline[name].bodies[0]);
  const d = draftOf(apple);
  assert.deepEqual(body(d), old("noop"));
  assert.deepEqual(body({ ...d, name: "AppleBot 二号" }), old("name"));
  assert.deepEqual(body(withFocusSymbols(d, ["AAPL", "MSFT"])), old("focus"));
  assert.deepEqual(body({ ...d, tool_scope: toggleTool(null, "create_forecast", NAMES) }), old("tools-one-off"));
  assert.deepEqual(body({ ...d, tool_scope: null }), old("tools-two-off-then-all"));
  assert.deepEqual(body({ ...d, model: "muse-ember" }), old("model"));
  assert.deepEqual(body({ ...d, look: { shape: "nuage", color: "orange" } }), old("look-shape"));
  assert.deepEqual(body({ ...d, look: { shape: "hexagone", color: "orange" } }), old("look-touched-back"));
  assert.deepEqual(body({ ...d, avatar: "🍎" }), old("emoji-avatar"));
  assert.deepEqual(body({ ...d, pinned: false, hidden: true }), old("pinned-hidden"));
  assert.deepEqual(body({ ...d, title: "苹果研究员", description: "只看 Apple。", group: "公司", daily_notify_cap: 9 }), old("title-description-group-cap"));
});
