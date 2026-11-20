import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { ID_PATTERN, MESSAGES, blankDraft, draftFromSource, dryRunView, generateId, healthKind, inputFromDraft, repairView, slugFromName, validateDraft, withName } from "../src/app/assistant/news/news-form.mjs";

const BASE = JSON.parse(readFileSync(new URL("../tools/shots/fixtures/assistant-bodies-baseline.json", import.meta.url), "utf8")).news;
const sentBody = (entry) => entry.sent[0].body;

test("an ID is made of the ASCII letters and digits of the name, lower case, with single hyphens, at most 80 long", () => {
  assert.equal(slugFromName("Markets Wire（示例）"), "markets-wire");
  assert.equal(slugFromName("  Yahoo Finance  "), "yahoo-finance");
  assert.equal(slugFromName("财联社 CLS 电报"), "cls");
  assert.equal(slugFromName("A--B__C"), "a-b-c");
  assert.equal(slugFromName("WSJ.com/markets"), "wsj-com-markets");
  assert.equal(slugFromName("x".repeat(100)).length, 80);
  assert.equal(slugFromName(`${"x".repeat(79)} y`).length, 79, "a hyphen left at the cut is dropped");
});

test("a name that gives fewer than 2 characters gives no ID", () => {
  assert.equal(slugFromName("财联社电报"), "");
  assert.equal(slugFromName("A"), "");
  assert.equal(slugFromName("（）"), "");
  assert.equal(slugFromName(""), "");
  assert.equal(slugFromName(undefined), "");
});

test("whatever a name is, the ID made of it passes the rule or is empty", () => {
  const names = ["Tech Daily", "财联社 CLS", "a", "日本語 News 日経", "!!!", "x".repeat(300), "A_B.C-D", "😀 Emoji 1", "ÀÉ café", "\n\t", "1", "12"];
  for (const name of names) { const id = generateId(name, []); assert.ok(id === "" || ID_PATTERN.test(id), `${JSON.stringify(name)} → ${id}`); }
});

test("a taken ID gets -2, -3 ... and the result stays within 80", () => {
  assert.equal(generateId("Tech Daily", ["tech-daily"]), "tech-daily-2");
  assert.equal(generateId("Tech Daily", ["tech-daily", "tech-daily-2"]), "tech-daily-3");
  const long = generateId("x".repeat(100), ["x".repeat(80)]);
  assert.equal(long.length, 80); assert.ok(long.endsWith("-2") && ID_PATTERN.test(long));
});

test("the ID follows the name until the reader types in the ID box", () => {
  let draft = withName(blankDraft(), "Tech Daily", ["wire"]);
  assert.equal(draft.id, "tech-daily");
  draft = withName(draft, "Tech Daily 2", ["wire"]);
  assert.equal(draft.id, "tech-daily-2");
  draft = withName({ ...draft, id: "mine", idTouched: true }, "Something Else", []);
  assert.equal(draft.id, "mine");
  assert.equal(withName(blankDraft(), "财联社电报", []).id, "", "an all-Chinese name leaves the ID empty");
});

test("a new form opens as the old one did", () => {
  assert.deepEqual(blankDraft(), { id: "", idTouched: false, name: "", kind: "rss", url: "", homepage: "", language: "zh-CN", markets: ["US"], tags: ["news"], alternates: [], reaRepair: true, enabled: true });
});

test("the rules: the old two sentences, and a new ID that is already taken", () => {
  const ok = { ...blankDraft(), id: "good-id", url: "https://example.test/x" };
  assert.deepEqual(validateDraft(ok), []);
  for (const id of ["a", "bad id", "", "新闻源", "x".repeat(81), "a/b"]) assert.deepEqual(validateDraft({ ...ok, id }).map((p) => p.field), ["id"], id);
  assert.equal(validateDraft({ ...ok, id: "a" })[0].message, MESSAGES.id);
  for (const url of ["ftp://x", "", "   ", "example.test", "http://"]) assert.deepEqual(validateDraft({ ...ok, url }).map((p) => p.field), ["url"], url);
  assert.equal(validateDraft({ ...ok, url: "ftp://x" })[0].message, "抓取地址须以 http:// 或 https:// 开头。");
  assert.equal(validateDraft({ ...ok, url: "HTTPS://example.test/x" }).length, 0, "the scheme is not case sensitive");
  assert.deepEqual(validateDraft({ ...ok, id: "wire" }, { existing: ["wire"] }), [{ field: "id", message: MESSAGES.idTaken }]);
  assert.deepEqual(validateDraft({ ...ok, id: "wire" }, { existing: ["wire"], editing: true }), [], "an existing source keeps its own ID");
  assert.equal(validateDraft({ ...blankDraft(), name: "财联社", url: "https://a.test" })[0].message, MESSAGES.idEmpty, "a name that gives no ID says so");
  assert.equal(validateDraft({ ...blankDraft(), name: "", url: "https://a.test" })[0].message, MESSAGES.id);
});

test("the body of a new source is the old form's: the defaults, the cleaned lists, homepage only when filled", () => {
  const body = (input) => JSON.stringify(inputFromDraft(input));
  assert.equal(body({ ...blankDraft(), id: "new-feed", url: "https://example.test/new.xml" }), sentBody(BASE.create.defaults));
  assert.equal(body({ ...blankDraft(), id: "  full-source  ", name: "  完整源  ", kind: "http_json", url: "  https://example.test/full.json  ", homepage: " https://example.test/ ", markets: ["us", "cn", "hk", "jp", "sg"], tags: ["macro", "flash", "ai", "earnings"], alternates: ["https://a.test/x.xml", "https://b.test/y.xml", "https://c.test/z"], reaRepair: false, enabled: false }), sentBody(BASE.create.everything));
  assert.equal(body({ ...blankDraft(), id: "html.src_2", kind: "http_html", url: "HTTPS://example.test/list", markets: [], tags: [] }), sentBody(BASE.create.html));
});

test("opening a source and saving it untouched sends what the old form sent for each of the six", () => {
  const sources = { "wire-markets": { id: "wire-markets", name: "Markets Wire（示例）", kind: "rss", url: "https://example.test/feeds/wire-markets.xml", homepage: "https://example.test/wire-markets", language: "en", tags: ["markets", "macro"], markets: ["US"], rea_repair: false, enabled: true, alternates: [] },
    "old-blog": { id: "old-blog", name: "旧博客（示例）", kind: "rss", url: "https://example.test/feeds/old-blog.xml", homepage: "https://example.test/old-blog", language: "zh", tags: ["markets"], markets: ["US"], rea_repair: false, enabled: false, alternates: [] },
    "chip-watch": { id: "chip-watch", name: "Chip Watch（示例）", kind: "http_html", url: "https://example.test/feeds/chip-watch.xml", homepage: "https://example.test/chip-watch", language: "en", tags: ["semiconductors"], markets: ["US"], rea_repair: true, enabled: true, alternates: [] } };
  for (const [id, source] of Object.entries(sources)) assert.equal(JSON.stringify(inputFromDraft(draftFromSource(source))), sentBody(BASE.edit[id]), id);
  const changed = { ...draftFromSource(sources["chip-watch"]), name: "芯片观察（改名）", markets: ["us", "tw"], tags: ["semis"], alternates: ["https://alt.test/a.xml"], homepage: "", reaRepair: false };
  assert.equal(JSON.stringify(inputFromDraft(changed)), sentBody(BASE.edit.changed));
});

test("a source with no markets or tags opens with the old defaults; language and a blank name behave as before", () => {
  const draft = draftFromSource({ id: "bare", name: "", kind: "rss", url: "https://x.test/" });
  assert.deepEqual([draft.markets, draft.tags, draft.alternates, draft.language, draft.reaRepair, draft.enabled], [["US"], ["news"], [], "zh-CN", true, true]);
  assert.equal(inputFromDraft(draft).name, "bare");
  assert.equal(inputFromDraft({ ...draft, language: "  " }).language, "zh-CN");
  assert.equal(inputFromDraft({ ...draft, markets: [" us ", "", "cn"], tags: [" a ", ""], alternates: ["", " https://x.test/a "] }).markets.join(), "US,CN");
});

test("a test fetch says what the old row said", () => {
  assert.deepEqual(dryRunView({ ok: true, raw_count: 24, valid_count: 22, sample: [{ title: "A", url: "u1", published_at: "2026-11-12T09:30:45Z" }, { title: "B", url: "u2", published_at: "2026-11-12T08:05:00Z" }, { title: "C", url: "u3", published_at: "x" }] }),
    { ok: true, raw: 24, valid: 22, samples: [{ title: "A", url: "u1", at: "2026-11-12T09:30" }, { title: "B", url: "u2", at: "2026-11-12T08:05" }] });
  assert.deepEqual(dryRunView({ ok: true }), { ok: true, raw: 0, valid: 0, samples: [] });
  assert.deepEqual(dryRunView({ ok: false, reason: "上游返回 503", error_code: "http_503" }), { ok: false, reason: "上游返回 503" });
  assert.deepEqual(dryRunView({ ok: false, error_code: "empty_feed" }), { ok: false, reason: "empty_feed" });
  assert.deepEqual(dryRunView({ ok: false }), { ok: false, reason: "" });
});

test("a repair says the sample count, or the code the server gave, or nothing (the page then says no spare source was found)", () => {
  assert.deepEqual(repairView({ ok: true, sample: [{}, {}] }), { ok: true, count: 2 });
  assert.deepEqual(repairView({ ok: true }), { ok: true, count: 0 });
  assert.deepEqual(repairView({ ok: false, error_code: "no_candidate_feed" }), { ok: false, reason: "no_candidate_feed" });
  assert.deepEqual(repairView({ ok: false }), { ok: false, reason: "" });
});

test("health is one of the three the server knows, or other", () => {
  assert.deepEqual(["ok", "degraded", "failed", "unknown", "", undefined].map(healthKind), ["ok", "degraded", "failed", "other", "other", "other"]);
});
