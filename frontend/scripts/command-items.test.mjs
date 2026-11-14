import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { addCandidate, arrange, botItems, companyItems, matchRank, pageItems, recentItems } from "../src/command-items.mjs";
import { PATTERNS } from "../src/routes.mjs";

const english = JSON.parse(await readFile(new URL("../src/locales/en-US.json", import.meta.url), "utf8"));
const en = (text) => english[text] ?? text;

const symbols = ["AAPL", "NVDA", "TSLA"];
const bots = [
  { id: "finbot", name: "FinBot", title: "主理", is_default: true, hidden: false },
  { id: "news-1", name: "NewsBot", title: "哨兵", hidden: false },
  { id: "old-2", name: "OldBot", title: "", hidden: true },
];
const recents = [{ id: "c1", title: "特斯拉财报怎么看" }, { id: "c2", title: "Portfolio check" }, { id: "c3", title: "" }];
const sources = (personal = true, t = (x) => x, locale = "zh-CN") => ({
  companies: companyItems(symbols, { locale }), bots: botItems(bots, { t }), pages: pageItems({ personal, t }), recents: recentItems(recents, { t }), symbols,
});
const first = (groups) => groups[0]?.rows[0];
const find = (groups, id) => groups.flatMap((group) => group.rows).find((row) => row.id === id);

test("match ranks: whole, start, word start, inside, none; empty query matches all", () => {
  assert.equal(matchRank("tsla", "TSLA"), 0);
  assert.equal(matchRank("ts", "TSLA"), 1);
  assert.equal(matchRank("bot", "FinBot"), 3);
  assert.equal(matchRank("bot", "全部 bot"), 2);
  assert.equal(matchRank("x", "TSLA"), -1);
  assert.equal(matchRank("", "anything"), 0);
  assert.equal(matchRank("  NV ", "nvda"), 1);
});

test("no query: the four groups in their default order, the recent list kept short", () => {
  const groups = arrange("", sources());
  assert.deepEqual(groups.map((group) => group.id), ["company", "bot", "page", "recent"]);
  assert.equal(groups[0].rows.length, 3);
  assert.equal(groups[1].rows.length, 3, "the hidden bot is listed");
  const many = Array.from({ length: 20 }, (_, i) => ({ id: `c${i}`, title: `T${i}` }));
  assert.equal(arrange("", { ...sources(), recents: recentItems(many) }).at(-1).rows.length, 8);
});

test("a ticker in the watch list comes first and Enter would open it", () => {
  const groups = arrange("nvda", sources());
  assert.equal(first(groups).id, "company:NVDA");
  assert.equal(first(groups).path, "/research/c/NVDA");
});

test("a valid ticker that is not on the list offers add-and-open; a prefix match still comes before it", () => {
  const amd = arrange("amd", sources());
  assert.equal(first(amd).id, "add:AMD");
  assert.equal(first(amd).path, "/research/c/AMD");
  const ts = arrange("TS", sources());
  assert.deepEqual(ts[0].rows.map((row) => row.id), ["company:TSLA", "add:TS"]);
  assert.equal(addCandidate("NVDA", symbols), null, "already on the list");
  assert.equal(addCandidate("not a ticker!", symbols), null);
  assert.equal(addCandidate("brk-b", symbols).symbol, "BRK.B");
  assert.equal(addCandidate("MSFT", Array.from({ length: 30 }, (_, i) => `A${String.fromCharCode(65 + (i % 26))}${i > 25 ? "B" : ""}`)), null, "a full list offers no add");
});

test("company names match: English name, Chinese name; the note follows the interface language", () => {
  assert.equal(first(arrange("tesla", sources())).id, "company:TSLA");
  assert.equal(first(arrange("英伟达", sources())).id, "company:NVDA");
  assert.equal(companyItems(["AAPL"], { locale: "zh-CN" })[0].note, "苹果");
  assert.equal(companyItems(["AAPL"], { locale: "en-US" })[0].note, "Apple");
});

test("a bot name leads to the bot (the default bot's address is /chat); a hidden bot is found and marked", () => {
  const news = arrange("news", sources());
  assert.equal(first(news).id, "bot:news-1");
  assert.equal(first(news).path, "/chat/news-1");
  assert.equal(first(arrange("finbot", sources())).path, "/chat");
  const old = first(arrange("old", sources(true, en, "en-US")));
  assert.equal(old.id, "bot:old-2");
  assert.equal(old.hidden, true);
  assert.equal(old.note, "Hidden");
});

test("a page name leads to the page, in the interface language; the Chinese name still works", () => {
  assert.equal(first(arrange("持仓", sources())).path, "/portfolio");
  const zh = first(arrange("材料库", sources()));
  assert.equal(zh.path.split("?")[0], "/research/materials");
  const enGroups = arrange("materials", sources(true, en, "en-US"));
  assert.equal(first(enGroups).path.split("?")[0], "/research/materials");
  assert.equal(first(enGroups).label, en("材料库"));
  assert.equal(first(arrange("材料库", sources(true, en, "en-US"))).path.split("?")[0], "/research/materials", "the Chinese phrase is a keyword");
  assert.equal(first(arrange("appearance", sources(true, en, "en-US"))).path, "/settings/appearance");
});

test("every page of the route table that has no parameter is offered, and each one is a route the app answers", () => {
  const pages = pageItems({ personal: true });
  const paths = pages.map((page) => page.path.split("?")[0]);
  const expected = Object.entries(PATTERNS).filter(([name, pattern]) => !pattern.includes(":") && !/^(login|devKit)/.test(name)).map(([, pattern]) => pattern);
  for (const pattern of expected) assert.ok(paths.includes(pattern), `missing page ${pattern}`);
  for (const section of ["models", "notifications", "appearance", "data", "account"]) assert.ok(paths.includes(`/settings/${section}`), section);
  assert.equal(new Set(pages.map((page) => page.id)).size, pages.length);
  for (const page of pages) assert.ok(page.area && page.label, page.path);
});

test("a guest is not offered the pages that need a login", () => {
  const guest = pageItems({ personal: false }).map((page) => page.path);
  for (const closed of ["/portfolio", "/routines", "/assistant/bots", "/assistant/skills"]) assert.ok(!guest.includes(closed), closed);
  for (const open of ["/chat", "/chat/history", "/research", "/research/forecasts", "/settings/models"]) assert.ok(guest.includes(open), open);
});

test("a recent conversation is found by its title and opens at its address; an untitled one gets a name", () => {
  const groups = arrange("财报", sources());
  assert.equal(first(groups).id, "recent:c1");
  assert.equal(first(groups).path, "/chat/c/c1");
  assert.equal(recentItems(recents, { t: en })[2].label, en("新对话"));
});

test("the group with the best match comes first, so the selected row is the best one", () => {
  const groups = arrange("portfolio", sources(true, en, "en-US"));
  assert.equal(groups[0].id === "page" || groups[0].id === "recent", true);
  assert.deepEqual(arrange("zzzz-nothing", { ...sources(), symbols: [] }).map((g) => g.id), [], "nothing matches, nothing listed");
});
