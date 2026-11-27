import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PANEL_DEFAULT, PANEL_MAX, PANEL_MIN, RECONCILE_NOTE, THREAD_MIN, availableTabs, clampPanelWidth, hasRoundContent, initialTab, roundQuestion, roundReconcile, roundSources, selectedIndex, storedPanelWidth, turnKey } from "../src/panel-model.mjs";
import { RECONCILE_NOTE as BACKSTAGE_NOTE } from "../src/backstage-view.mjs";

const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");

test("a bot's page has three tabs (the profile is its settings page since P5.1), a conversation with no bot only sources and process", () => {
  assert.deepEqual(availableTabs({ hasWorkspace: true }), ["sources", "process", "workspace"]);
  assert.deepEqual(availableTabs({ hasWorkspace: true, hasProfile: true }), ["sources", "process", "workspace"], "a profile tab is not offered any more");
  assert.deepEqual(availableTabs({}), ["sources", "process"]);
});

test("the first tab is the stored one, 工作区 by default, 来源 where there is no workspace; a stored 档案 (the tab that was) is ignored", () => {
  const bot = availableTabs({ hasWorkspace: true });
  assert.equal(initialTab(null, bot), "workspace");
  assert.equal(initialTab("process", bot), "process");
  assert.equal(initialTab("profile", bot), "workspace");
  assert.equal(initialTab("nonsense", bot), "workspace");
  assert.equal(initialTab("workspace", availableTabs({})), "sources");
  assert.equal(initialTab(null, availableTabs({})), "sources");
});

test("the width stays inside its limits and leaves the thread its room", () => {
  assert.equal(clampPanelWidth(100), PANEL_MIN);
  assert.equal(clampPanelWidth(5000), PANEL_MAX);
  assert.equal(clampPanelWidth(480.4), 480);
  assert.equal(clampPanelWidth(NaN), PANEL_DEFAULT);
  assert.equal(clampPanelWidth(700, 1000), 1000 - THREAD_MIN);
  assert.equal(clampPanelWidth(700, 500), PANEL_MIN);
});

test("a stored width is read only when it is a plain number", () => {
  assert.equal(storedPanelWidth("520"), 520);
  assert.equal(storedPanelWidth(null), PANEL_DEFAULT);
  assert.equal(storedPanelWidth("wide"), PANEL_DEFAULT);
  assert.equal(storedPanelWidth("90"), PANEL_MIN);
});

const messages = [
  { role: "user", content: "AAPL 最近一个季度的服务收入怎么样？请详细说明并给出来源，越详细越好，谢谢" },
  { role: "assistant", turn_id: "t1", content: "a", citations: [{ ordinal: 1, title: "x" }] },
  { role: "user", content: "第二个问题" },
  { role: "assistant", turn_id: "t2", content: "" },
  { role: "assistant", content: "后一条", status: "complete" },
];

test("a round's key is the turn id, else its place", () => {
  assert.equal(turnKey(messages[1], 1), "t1");
  assert.equal(turnKey(messages[4], 4), "#4");
});

test("an answer with nothing in it is not a round the panel can show", () => {
  assert.equal(hasRoundContent(messages[1]), true);
  assert.equal(hasRoundContent(messages[3]), false);
  assert.equal(hasRoundContent(messages[0]), false);
  assert.equal(hasRoundContent({ role: "assistant", content: "", thinking_ms: 0 }), true);
});

test("the selected round is the one asked for, else the newest with content", () => {
  assert.equal(selectedIndex(messages, "t1"), 1);
  assert.equal(selectedIndex(messages, "#4"), 4);
  assert.equal(selectedIndex(messages, null), 4);
  assert.equal(selectedIndex(messages, "gone"), 4);
  assert.equal(selectedIndex([{ role: "user", content: "x" }], null), -1);
  assert.equal(selectedIndex([], "t1"), -1);
});

test("the question of a round is the user message before it, cut short", () => {
  assert.equal(roundQuestion(messages, 1, 10), "AAPL 最近一个季…");
  assert.equal(roundQuestion(messages, 3), "第二个问题");
  assert.equal(roundQuestion(messages, 4), "");
  assert.equal(roundQuestion([{ role: "assistant", content: "x" }], 0), "");
});

test("the sources are what the old drawer listed: all of them under protocol 1, the issued nodes under protocol 2", () => {
  const citations = [{ ordinal: 1, title: "a" }, { ordinal: 2, title: "b" }];
  assert.equal(roundSources({ citations }).length, 2);
  assert.deepEqual(roundSources({ citation_protocol: "v2", citations, citation_nodes: [{ source_ref: "2" }] }).map((c) => c.title), ["b"]);
  assert.deepEqual(roundSources(null), []);
});

// ---- 5d-1 Task 5: the figure check in the 出处 tab ----------------------------------------------------------------------

test("a flagged check: the title, how many were checked, each line with its values, and the backstage's fixed note", () => {
  const block = roundReconcile({ role: "assistant", content: "x", reconciliation: { version: 1, figures: 3,
    flagged: [{ line: "利润是 8888 美元，现金是 9999 美元", values: ["8888", "9999"] }, { line: " ", values: ["1"] }, "junk", { line: "毛利 7 美元", values: [7, "7"] }] } });
  assert.deepEqual(block, { kind: "flagged", title: "数字对账", intro: "这一轮核对了 3 个数字，下面这些在这一轮读到的资料里都找不到：",
    lines: [{ line: "利润是 8888 美元，现金是 9999 美元", values: ["8888", "9999"] }, { line: "毛利 7 美元", values: ["7"] }],
    note: "这些数字在这一轮读到的资料里都找不到；不一定是错，可能是模型自己的知识或算法，请对照原文判断。" });
  assert.equal(RECONCILE_NOTE, BACKSTAGE_NOTE, "the same words as the backstage");
});

test("a clean check is one quiet line; an unchecked, failed or figure-less answer shows nothing", () => {
  assert.deepEqual(roundReconcile({ reconciliation: { version: 1, figures: 2, flagged: [] } }), { kind: "clean", text: "数字对账：这一轮的 2 个数字都在资料里找得到。" });
  assert.equal(roundReconcile({ role: "assistant", content: "x" }), null, "not checked");
  assert.equal(roundReconcile({ reconciliation: null }), null);
  assert.equal(roundReconcile({ reconciliation: { version: 1, error: "KeyError" } }), null, "a failed check is the backstage's business");
  assert.equal(roundReconcile({ reconciliation: { version: 1, figures: 0, flagged: [] } }), null, "no figure, nothing to say");
  assert.equal(roundReconcile({ reconciliation: { version: 1, flagged: [{ line: "l", values: ["1"] }] } }), null, "no count, not a result");
  assert.equal(roundReconcile(null), null);
});

test("the phrases go through t and {n} is filled after", () => {
  const t = (phrase) => `<${phrase}>`;
  const flagged = roundReconcile({ reconciliation: { figures: 1, flagged: [{ line: "l", values: ["1"] }] } }, t);
  assert.equal(flagged.title, "<数字对账>");
  assert.equal(flagged.intro, "<这一轮核对了 1 个数字，下面这些在这一轮读到的资料里都找不到：>");
  assert.equal(flagged.note, `<${RECONCILE_NOTE}>`);
  assert.equal(roundReconcile({ reconciliation: { figures: 4, flagged: [] } }, t).text, "<数字对账：这一轮的 4 个数字都在资料里找得到。>");
});

test("every phrase of the 出处 tab's figure check is in both catalogs", () => {
  const chinese = JSON.parse(src("locales/zh-CN.json")), english = JSON.parse(src("locales/en-US.json"));
  for (const phrase of ["数字对账", "这一轮核对了 {n} 个数字，下面这些在这一轮读到的资料里都找不到：", "数字对账：这一轮的 {n} 个数字都在资料里找得到。", RECONCILE_NOTE]) {
    assert.ok(chinese.includes(phrase), phrase);
    assert.ok(english[phrase]?.trim(), phrase);
    if (phrase.includes("{n}")) assert.ok(english[phrase].includes("{n}"), `the English of ${phrase} keeps {n}`);
  }
});

test("the 出处 tab closes with the check, also under the empty line, and nothing in the answer text reads it", () => {
  const tab = src("app/chat/SourcesTab.tsx");
  assert.match(tab, /const block = roundReconcile\(m, t\);/);
  assert.match(tab, /data-testid="reconcile-note" role="note"/);
  assert.match(tab, /data-testid="reconcile-line"/);
  assert.match(tab, /data-testid="reconcile-clean"/);
  assert.equal(tab.match(/<Reconcile m=\{m\} \/>/g)?.length, 2, "after the cards and after 「这一轮没有引用来源。」");
  for (const name of ["AgentChatPanel.tsx", "app/chat/ProcessTab.tsx"]) {
    try { assert.doesNotMatch(src(name), /reconciliation|roundReconcile/, name); } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
});
