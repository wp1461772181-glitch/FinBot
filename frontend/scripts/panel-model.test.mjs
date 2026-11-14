import test from "node:test";
import assert from "node:assert/strict";
import { PANEL_DEFAULT, PANEL_MAX, PANEL_MIN, THREAD_MIN, availableTabs, clampPanelWidth, hasRoundContent, initialTab, roundQuestion, roundSources, selectedIndex, storedPanelWidth, turnKey } from "../src/panel-model.mjs";

test("a bot's page has four tabs, a conversation with no bot only sources and process", () => {
  assert.deepEqual(availableTabs({ hasWorkspace: true, hasProfile: true }), ["sources", "process", "workspace", "profile"]);
  assert.deepEqual(availableTabs({}), ["sources", "process"]);
});

test("the first tab is the stored one, 工作区 by default, 来源 where there is no workspace; 档案 is never restored from storage", () => {
  const bot = availableTabs({ hasWorkspace: true, hasProfile: true });
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
