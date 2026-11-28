import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { blankEditor, editorOf, exportName, hasSwitch, inputOf, isEditable, linkTarget, saveOf, toggleTool } from "../src/app/assistant/skills/skill-form.mjs";
import { canSaveEdit, isInferred, memoryTab, scopeChoices } from "../src/app/assistant/memory/memory-view.mjs";
import { SOURCES, isDerivedText, localDateTimeInput, parseLocalDateTime, retrievalArgs, retrievalKind, retrievalText, uploadReady } from "../src/app/assistant/knowledge/knowledge-form.mjs";

const BASE = JSON.parse(readFileSync(new URL("../tools/shots/fixtures/assistant-bodies-baseline.json", import.meta.url), "utf8"));
const sent = (entry, index = 0) => entry.sent[index].body;
const SKILLS = [{ id: "s1", name: "财报速读", builtin: true, status: "active" }, { id: "s2", name: "周日复盘", builtin: false, status: "active", description: "检查持仓计划与本周财报判断", body: "1. 读取持仓。\n2. 对照价格计划。\n3. 列出下周要关注的事项。", allowed_tools: ["query_portfolio", "get_market_data"], output_template: null }, { id: "s4", name: "估值草稿", builtin: false, status: "draft", description: "未完成的草稿：用可比公司做粗估", body: "（草稿）", allowed_tools: ["get_market_data"], output_template: null }];

test("a new skill is created enabled with the old body, key for key", () => {
  const c = BASE.skills.create;
  const save = (input) => JSON.stringify(saveOf({ ...blankEditor(), ...input }).body);
  assert.equal(save({ name: "  新技能一  ", description: "  说明一句  ", body: "步骤1\n步骤2", tools: ["get_market_data"] }), sent(c.minimal));
  assert.equal(save({ name: "带模板", description: "d", body: "b", template: "## 要点\n## 风险", tools: ["read_filing", "get_market_data"] }), sent(c.withTemplate));
  assert.equal(save({ name: "全部工具", description: "全部", body: "x", template: "  ", tools: ["get_market_data", "search_news", "read_filing", "query_portfolio", "save_material"] }), sent(c.allTools));
  assert.equal(save({ name: "没有工具", description: "无", body: "z" }), sent(c.noTools));
  assert.equal(saveOf(blankEditor()).create, true);
});

test("an edit sends the old body (no enabled); a draft that is saved adds save_draft", () => {
  const edit = saveOf(editorOf(SKILLS[1]));
  assert.equal(edit.create, false); assert.equal(edit.id, "s2");
  assert.equal(JSON.stringify(edit.body), sent(BASE.skills.edit.untouched));
  assert.equal(JSON.stringify(saveOf({ ...editorOf(SKILLS[1]), name: "周日复盘 v2", description: "改过的说明" }).body), sent(BASE.skills.edit.rename));
  const draft = saveOf(editorOf(SKILLS[2]));
  assert.equal(JSON.stringify(draft.body), sent(BASE.skills.draft));
  assert.equal(draft.body.save_draft, true);
  assert.equal("enabled" in edit.body, false);
});

test("ticking a tool appends it, unticking removes it, the order is the order of the ticks", () => {
  assert.deepEqual(toggleTool(toggleTool([], "b", true), "a", true), ["b", "a"]);
  assert.deepEqual(toggleTool(["b", "a"], "b", false), ["a"]);
  assert.deepEqual(toggleTool(["a"], "a", true), ["a"]);
});

test("an address asks for a skill's editor; a missing one is said; a built-in has none", () => {
  assert.deepEqual(linkTarget(SKILLS, null), { kind: "none" });
  assert.equal(linkTarget(SKILLS, "s4").kind, "editor");
  assert.equal(linkTarget(SKILLS, "s2").kind, "editor");
  assert.deepEqual(linkTarget(SKILLS, "s1"), { kind: "builtin" });
  assert.deepEqual(linkTarget(SKILLS, "zz"), { kind: "missing" });
  assert.deepEqual([hasSwitch(SKILLS[0]), hasSwitch(SKILLS[2]), isEditable(SKILLS[0]), isEditable(SKILLS[2]), exportName(SKILLS[1])], [true, false, false, true, "周日复盘.md"]);
  assert.equal(inputOf({ ...blankEditor(), template: "   " }).output_template, null);
});

test("the memory page's tab is in the address: recall, or the profile for anything else", () => {
  assert.deepEqual(["recall", "profile", "", null, undefined, "x", "RECALL"].map(memoryTab), ["recall", "profile", "profile", "profile", "profile", "profile", "profile"]);
  assert.deepEqual([isInferred({ origin: "inferred" }), isInferred({ origin: "explicit" }), isInferred({ origin: "manual" })], [true, false, false]);
  assert.deepEqual(scopeChoices({ bot_id: "x" }, [{ id: "a" }]), { bots: [{ id: "a" }], gone: true });
  assert.deepEqual(scopeChoices({ bot_id: "a" }, [{ id: "a" }]).gone, false);
  assert.equal(scopeChoices({ bot_id: null }, []).gone, false);
  assert.deepEqual([canSaveEdit("  "), canSaveEdit(" a ")], [false, true]);
});

test("an upload's time is the local time of the box, and a made-up one is refused", () => {
  assert.equal(parseLocalDateTime("2026-11-10T09:30")?.getHours(), 9);
  for (const bad of ["", "2026-02-30T10:00", "2026-13-01T10:00", "2026-11-10 09:30", "2026-11-10T25:00", null]) assert.equal(parseLocalDateTime(bad), null, String(bad));
  assert.equal(localDateTimeInput(new Date(2026, 0, 2, 3, 4)), "2026-01-02T03:04");
  assert.equal(parseLocalDateTime(localDateTimeInput(new Date(2026, 5, 7, 8, 9)))?.getMinutes(), 9);
  const iso = BASE.knowledge.upload.markdown.sent[0].fields.published_at;
  assert.match(iso, /Z$/);
});

test("the retrieval test's kind comes from the source; 常见问题 sends no code; the body is the old one", () => {
  assert.deepEqual(SOURCES.map((s) => retrievalKind(s.value)), ["faq", "material", "material", "analysis"]);
  for (const [key, source, symbol] of [["upload-AAPL", "upload", "AAPL"], ["faq-AAPL", "faq", "AAPL"], ["analysis-TSLA", "analysis", "TSLA"], ["sec-NVDA", "sec", "NVDA"]]) {
    const [kind, keyword, code] = retrievalArgs(source, "服务收入", symbol);
    assert.equal(JSON.stringify({ kind, keyword, ...(code ? { symbol: code } : {}) }), sent(BASE.knowledge.retrieval[key]), key);
  }
});

test("an upload is ready with a file, title, link and reason; AI-derived text is marked by its first words", () => {
  const all = { file: {}, title: "t", url: "u", reason: "r" };
  assert.equal(uploadReady(all), true);
  for (const k of Object.keys(all)) assert.equal(uploadReady({ ...all, [k]: k === "file" ? null : "" }), false, k);
  assert.equal(isDerivedText("派生 AI 分析；以下"), true);
  assert.equal(isDerivedText("Services revenue"), false);
  assert.equal(retrievalText({ result: { ok: true }, citations: [] }), '{\n  "result": {\n    "ok": true\n  },\n  "citations": []\n}');
  assert.equal(retrievalText({ result: { ok: true, data: [{ title: "AAPL 10-Q（2026 财年第四季度）", snippet: "Services revenue grew year over year.", score: 0.83 }] }, citations: [{ index: 1, title: "AAPL 10-Q（2026 财年第四季度）", url: "https://example.test/docs/01" }] }), BASE.knowledge.retrieval["upload-AAPL"].pre);
});

// 11-28 活人感: 相处方式 and 近况 are shown apart; a 近况 has no 确认.
import { KIND_LABELS, KINDS, canConfirm, isPortrait } from "../src/app/assistant/memory/memory-view.mjs";
import { manualItemDraft } from "../src/memory-items.mjs";
test("style and recent are kinds of their own, shown apart, and a recent one needs no confirmation", () => {
  assert.equal(KIND_LABELS.style, "相处方式");
  assert.equal(KIND_LABELS.recent, "近况");
  assert.ok(KINDS.includes("style") && KINDS.includes("recent"));
  assert.equal(isPortrait({ kind: "recent", status: "active" }), true);
  assert.equal(isPortrait({ kind: "style", status: "proposed" }), false);
  assert.equal(isPortrait({ kind: "preference", status: "active" }), false);
  assert.equal(canConfirm({ kind: "recent", origin: "inferred" }), false);
  assert.equal(canConfirm({ kind: "style", origin: "inferred" }), true);
  assert.ok(manualItemDraft({ kind: "style", text: "说话轻松点" }).fields);
});
