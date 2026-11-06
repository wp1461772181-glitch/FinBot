import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { EFFORT_LEVELS, effortChoices, effortLabel, modelChoices, patchFor, badgeText } from "../src/model-effort.mjs";

const tsx = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");
const css = readFileSync(new URL("../src/chat.css", import.meta.url), "utf8");
const catalog = {
  default: "alpha",
  models: [
    { name: "alpha", display_name: "Alpha", model: "a/x", key_status: "configured" },
    { name: "beta", display_name: "Beta", model: "b/y", key_status: "missing" },
    { name: "gamma", display_name: "Gamma", model: "g/z", key_status: "configured" },
  ],
};

test("tiers: the browser lists exactly the tiers the server accepts, in the server's order", () => {
  const server = readFileSync(new URL("../../app/agent_chat_provider.py", import.meta.url), "utf8");
  const declared = server.match(/^REASONING_EFFORTS = \((.*?)\)/m)?.[1].match(/"([a-z]+)"/g).map((s) => s.slice(1, -1));
  assert.deepEqual([...EFFORT_LEVELS], declared);
  assert.deepEqual([...EFFORT_LEVELS], ["none", "minimal", "low", "medium", "high", "xhigh", "max"]);
});

test("labels: null is the default, each tier has its Chinese label", () => {
  assert.equal(effortLabel(null), "默认");
  assert.deepEqual(EFFORT_LEVELS.map(effortLabel), ["无", "极简", "低", "中", "高", "极高", "最高"]);
});

test("effort choices: default first, every tier after it, only the current one ticked, none disabled", () => {
  const high = effortChoices("high");
  assert.deepEqual(high.map((c) => c.value), [null, ...EFFORT_LEVELS]);
  assert.deepEqual(high.filter((c) => c.checked).map((c) => c.value), ["high"]);
  assert.ok(high.every((c) => !c.disabled));
  assert.deepEqual(effortChoices(null).filter((c) => c.checked).map((c) => c.value), [null]);
  assert.deepEqual(effortChoices(undefined).filter((c) => c.checked).map((c) => c.value), [null]);
});

test("model choices: server default first, then configured entries only, ticked where they are current", () => {
  const forDefault = modelChoices(catalog, null);
  assert.deepEqual(forDefault.map((c) => c.value), [null, "alpha", "gamma"]);
  assert.equal(forDefault[0].checked, true);
  assert.equal(forDefault[1].label, "Alpha · a/x");
  assert.deepEqual(modelChoices(catalog, "gamma").filter((c) => c.checked).map((c) => c.value), ["gamma"]);
});

test("model choices: a current model whose key is missing still shows, marked, so the owner sees it", () => {
  const choices = modelChoices(catalog, "beta");
  const beta = choices.find((c) => c.value === "beta");
  assert.ok(beta, "the current entry is listed");
  assert.equal(beta.checked, true);
  assert.equal(beta.keyMissing, true);
});

test("a choice is saved as the one field it changes", () => {
  assert.deepEqual(patchFor("model", "alpha"), { model: "alpha" });
  assert.deepEqual(patchFor("model", null), { model: null });
  assert.deepEqual(patchFor("effort", "xhigh"), { reasoning_effort: "xhigh" });
  assert.deepEqual(patchFor("effort", null), { reasoning_effort: null });
});

test("badge: 模型 · name · strength label, and the default words when unset", () => {
  const t = (s) => s;
  assert.equal(badgeText({ model: "alpha", reasoning_effort: "xhigh" }, t), "模型 · alpha · 极高");
  assert.equal(badgeText({ model: null, reasoning_effort: null }, t), "模型 · 服务器默认模型 · 默认");
  assert.equal(badgeText({ model: "alpha", reasoning_effort: null }, t), "模型 · alpha · 默认");
  assert.equal(badgeText({ model: "alpha", reasoning_effort: "max" }, (s) => `[${s}]`), "[模型] · alpha · [最高]");
});

test("picker is wired to the chat badge: updateBot with the changed field only, a visible error, no false success", () => {
  const picker = tsx("ModelEffortPicker.tsx");
  assert.match(picker, /updateBot\(bot\.id, patchFor\(/);
  assert.match(picker, /role="alert"/);
  assert.match(picker, /catch/);
  assert.match(tsx("AgentChatPanel.tsx"), /<ModelEffortPicker/);
  assert.match(tsx("App.tsx"), /onBotChanged=\{onChanged\}/);
  assert.match(css, /\.model-effort-pop\s*\{/);
});
