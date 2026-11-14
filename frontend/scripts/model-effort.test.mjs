import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { EFFORT_LEVELS, badgeText, effectiveEntry, effortChoices, effortLabel, effortSupport, modelChoices, noEffort, patchFor } from "../src/model-effort.mjs";

const tsx = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");
const css = readFileSync(new URL("../src/styles/legacy/chat.css", import.meta.url), "utf8");
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

// --- strength tiers follow the model the badge shows (OpenRouter's reasoning block, via /model-catalog) ---

const ALL = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];
const withSupport = (fields) => ({ name: "m", display_name: "M", model: "v/m", key_status: "configured", ...fields });
const values = (choices) => choices.map((c) => c.value);

test("the badge's model: the bot's own entry, else the server default entry; unknown is null", () => {
  assert.equal(effectiveEntry(catalog, "gamma").name, "gamma");
  assert.equal(effectiveEntry(catalog, null).name, "alpha");
  assert.equal(effectiveEntry(catalog, "nope"), null);
  assert.equal(effectiveEntry({ default: null, models: [] }, null), null);
  assert.equal(effectiveEntry(null, "alpha"), null);
});

test("tiers, supported list: only the listed tiers after 默认, in the display order, ticked where current", () => {
  const entry = withSupport({ reasoning_supported: true, supported_efforts: ["max", "high", "low", "none"] });
  assert.deepEqual(effortSupport(entry).levels, ["none", "low", "high", "max"]);
  assert.deepEqual(values(effortChoices("high", entry)), [null, "none", "low", "high", "max"]);
  assert.deepEqual(effortChoices("high", entry).filter((c) => c.checked).map((c) => c.value), ["high"]);
  assert.equal(noEffort(entry), false);
  // Tiers the list does not name, and any the server does not know, never appear.
  const narrow = withSupport({ reasoning_supported: true, supported_efforts: ["high", "medium", "none", "bogus"] });
  assert.deepEqual(values(effortChoices(null, narrow)), [null, "none", "medium", "high"]);
  assert.ok(effortChoices(null, narrow).every((c) => !c.unsupported));
});

test("tiers, null or unknown: every tier (the fallback), so an unknown model keeps the full list", () => {
  const accepts_all = withSupport({ reasoning_supported: true, supported_efforts: null });
  const missing = withSupport({});
  assert.deepEqual(values(effortChoices("medium", accepts_all)), [null, ...ALL]);
  assert.deepEqual(values(effortChoices("medium", missing)), [null, ...ALL]);
  assert.deepEqual(values(effortChoices("medium", null)), [null, ...ALL]);
  assert.deepEqual(values(effortChoices("medium")), [null, ...ALL]);
  assert.equal(noEffort(missing), false);
  assert.equal(noEffort(null), false);
});

test("tiers, model takes no reasoning effort: only 默认 is offered and the panel says so", () => {
  const plain = withSupport({ reasoning_supported: false });
  assert.deepEqual(values(effortChoices(null, plain)), [null]);
  assert.deepEqual(effortChoices(null, plain).map((c) => c.checked), [true]);
  assert.equal(noEffort(plain), true);
  assert.deepEqual(effortSupport(plain).levels, []);
});

test("tiers, stored value the model does not take: shown at the top, ticked and marked, nothing silently dropped or changed", () => {
  const entry = withSupport({ reasoning_supported: true, supported_efforts: ["high", "none"] });
  const choices = effortChoices("xhigh", entry);
  assert.deepEqual(values(choices), ["xhigh", null, "none", "high"]);
  assert.equal(choices[0].unsupported, true);
  assert.equal(choices[0].checked, true);
  assert.deepEqual(choices.filter((c) => c.checked).map((c) => c.value), ["xhigh"]);
  assert.equal(choices[0].label, "极高");
  // A model that takes no effort at all still shows the stored value above 默认.
  const plain = withSupport({ reasoning_supported: false });
  assert.deepEqual(values(effortChoices("low", plain)), ["low", null]);
  assert.equal(effortChoices("low", plain)[0].unsupported, true);
});

test("tiers, stored value the model takes: no duplicate row, ordinary tick", () => {
  const entry = withSupport({ reasoning_supported: true, supported_efforts: ["high", "none"] });
  const choices = effortChoices("high", entry);
  assert.equal(choices.filter((c) => c.value === "high").length, 1);
  assert.ok(choices.every((c) => !c.unsupported));
});

test("tiers: the picker reads the effective entry and passes it to the strength list", () => {
  const picker = tsx("ModelEffortPicker.tsx");
  assert.match(picker, /effectiveEntry\(catalog, shown\.model\)/);
  assert.match(picker, /effortChoices\(shown\.reasoning_effort, entry\)/);
  assert.match(picker, /noEffort\(entry\)/);
  assert.match(picker, /choice\.unsupported && <small>[^<]*不在该模型的档位内/);
});

test("tiers, zhipu shape (GLM-5.3 family): exactly low, high, max; a stored medium sits above them, marked", () => {
  const zhipu = withSupport({ reasoning_supported: true, supported_efforts: ["low", "high", "max"] });
  assert.deepEqual(effortSupport(zhipu).levels, ["low", "high", "max"]);
  assert.deepEqual(values(effortChoices("high", zhipu)), [null, "low", "high", "max"]);
  const stored = effortChoices("medium", zhipu);
  assert.deepEqual(values(stored), ["medium", null, "low", "high", "max"]);
  assert.equal(stored[0].unsupported, true);
});

test("picking a model keeps the panel open on the new model's tiers; picking a strength closes it", () => {
  const picker = tsx("ModelEffortPicker.tsx");
  const choose = picker.slice(picker.indexOf("async function choose("), picker.indexOf("\n  return (\n"));
  assert.ok(choose.length > 0, "choose() is found in the picker source");
  // Same choice again: closes, as before.
  assert.match(choose, /if \(\(value \?\? null\) === \(current \?\? null\)\) \{ setOpen\(false\); return; \}/);
  // After a successful save the model choice leaves the panel open; only a strength closes it.
  assert.match(choose, /setShown\(saved\);\s*(?:\/\/[^\n]*\s*)?if \(kind === "effort"\) setOpen\(false\);/);
});
