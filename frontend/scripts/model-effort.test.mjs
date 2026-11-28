import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { EFFORT_LEVELS, LOGO_KEYS, badgeText, effectiveEntry, effortBars, effortChoices, effortHigh, effortHint, effortLabel, effortSupport, effortTone, entryLogo, modelChoices, modelSections, noEffort, patchFor, providerLabel, providerLogo, triggerView } from "../src/model-effort.mjs";

const tsx = (f) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");
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
  const picker = tsx("app/chat/ModelEffortPicker.tsx");
  assert.match(picker, /updateBot\(bot\.id, patchFor\(/);
  assert.match(tsx("app/chat/ModelEffortPanel.tsx"), /role="alert"/);   // the reason is drawn by the panel (it owns no state: the picker passes `error`)
  assert.match(picker, /catch/);
  assert.match(tsx("app/chat/Composer.tsx"), /<ModelEffortPicker/);   // P3.2: the badge sits in the composer's tool row
  assert.match(tsx("app/pages/chat.tsx"), /onBotChanged=\{changed\}/);   // P2.1: BotPage moved from App.tsx
  // The panel is a centred palette (a drawer on a phone) in a chunk of its own: the composer imports it lazily, never statically.
  assert.match(picker, /import\("\.\/ModelEffortPanel"\)/);
  assert.doesNotMatch(picker, /from "\.\/ModelEffortPanel"/);
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

test("no effort choice anywhere: the composer's selector and the bot settings offer the model only and say depth is the model's call (11-28)", () => {
  const picker = tsx("app/chat/ModelEffortPicker.tsx");
  const panel = tsx("app/chat/ModelEffortPanel.tsx");
  const form = tsx("app/bot-settings/FormSections.tsx");
  assert.match(picker, /effectiveEntry\(catalog, shown\.model\)/);
  for (const source of [panel, form]) {
    assert.doesNotMatch(source, /effortChoices\(|role="radiogroup"|effort-select|effort-seg/);
    assert.doesNotMatch(source, /t\("推理强度"\)/);
  }
  assert.match(panel, /t\("思考深度不用选：它按每个问题自己决定，从浅到深。"\)/);
  assert.match(form, /t\("思考深度不用设置：它按每个问题自己决定，从浅到深。"\)/);
  assert.doesNotMatch(picker, /view\.bars|view\.level|推理强度/);
});

test("tiers, zhipu shape (GLM-5.3 family): exactly low, high, max; a stored medium sits above them, marked", () => {
  const zhipu = withSupport({ reasoning_supported: true, supported_efforts: ["low", "high", "max"] });
  assert.deepEqual(effortSupport(zhipu).levels, ["low", "high", "max"]);
  assert.deepEqual(values(effortChoices("high", zhipu)), [null, "low", "high", "max"]);
  const stored = effortChoices("medium", zhipu);
  assert.deepEqual(values(stored), ["medium", null, "low", "high", "max"]);
  assert.equal(stored[0].unsupported, true);
});

test("picking a model closes the panel (there is no strength row below it any more)", () => {
  const picker = tsx("app/chat/ModelEffortPicker.tsx");
  const choose = picker.slice(picker.indexOf("async function choose("), picker.indexOf("\n  return (\n"));
  assert.ok(choose.length > 0, "choose() is found in the picker source");
  // Same choice again: closes, as before.
  assert.match(choose, /if \(\(value \?\? null\) === \(current \?\? null\)\) \{ setOpen\(false\); return; \}/);
  assert.match(choose, /setShown\(saved\);\s*setOpen\(false\);/);
});

// --- the composer's model selector (palette + strength control): logos, groups, the badge's parts, and what the sources must keep ---

const pickerCatalog = {
  default: "haiku",
  models: [
    { name: "haiku", display_name: "Haiku 5.5", provider: "openrouter", model: "anthropic/claude-haiku-5.5", key_status: "configured", reasoning_supported: true },
    { name: "terra", display_name: "GPT-6.1 Terra", provider: "openrouter", model: "openai/gpt-6.1-terra", key_status: "missing" },
    { name: "ember", display_name: "Muse Ember", provider: "openrouter", model: "muse/ember", key_status: "configured" },
    { name: "flash", display_name: "DeepSeek Flash", provider: "siliconflow", model: "deepseek-ai/DeepSeek-V4-Flash", key_status: "configured" },
    { name: "glm", display_name: "GLM", provider: "zhipu", model: "glm-5.3-flash", key_status: "configured" },
    { name: "mine", display_name: "Mine", provider: "custom", model: "x", key_status: "configured" },
  ],
};

test("logos: an OpenRouter entry shows its model's vendor by the id's prefix, any other entry its provider's own, and the rest nothing (the generic mark)", () => {
  assert.equal(entryLogo(pickerCatalog.models[0]), "anthropic");
  assert.equal(entryLogo(pickerCatalog.models[1]), "openai");
  assert.equal(entryLogo({ provider: "openrouter", model: "x-ai/grok-5" }), "xai");
  assert.equal(entryLogo({ provider: "openrouter", model: "mistralai/mistral-large" }), "mistral");
  assert.equal(entryLogo({ provider: "openrouter", model: "z-ai/glm-5" }), "zhipuai");
  assert.equal(entryLogo({ provider: "openrouter", model: "~anthropic/claude-latest" }), "anthropic");
  assert.equal(entryLogo(pickerCatalog.models[2]), null, "an unknown vendor prefix: generic, not the OpenRouter mark");
  assert.equal(entryLogo(pickerCatalog.models[3]), "siliconflow", "not OpenRouter: the provider's own logo, whatever the id says");
  assert.equal(entryLogo(pickerCatalog.models[4]), "zhipuai");
  assert.equal(entryLogo(pickerCatalog.models[5]), null);
  assert.equal(entryLogo({ provider: "openrouter" }), null);
  assert.equal(entryLogo(null), null);
  assert.equal(providerLogo("kimi"), "moonshotai");
  assert.equal(providerLogo("qwen"), "alibaba");
  assert.equal(providerLogo("doubao"), null);
  assert.equal(providerLogo(undefined), null);
});

test("logos: every key the mapping can return is a shipped file, the generic mark exists, and no logo is loaded from outside", () => {
  const dir = new URL("../src/assets/provider-logos/", import.meta.url);
  for (const key of [...LOGO_KEYS, "generic"]) assert.ok(existsSync(new URL(`${key}.svg`, dir)), `${key}.svg is missing`);
  const mapped = ["deepseek", "kimi", "minimax", "qwen", "zhipu", "doubao", "hunyuan", "baidu", "siliconflow", "openrouter", "custom", "anthropic", "openai", "google", "xai", "mistral", "groq"].map(providerLogo).filter(Boolean);
  for (const key of mapped) assert.ok(LOGO_KEYS.includes(key), `${key} is not a shipped logo`);
  for (const vendor of ["anthropic", "openai", "google", "x-ai", "mistralai", "deepseek", "moonshotai", "qwen", "z-ai", "meta-llama", "minimax", "nvidia", "perplexity", "cohere"]) {
    assert.ok(LOGO_KEYS.includes(entryLogo({ provider: "openrouter", model: `${vendor}/m` })), `${vendor} has no shipped logo`);
  }
  for (const file of ["components/ai-elements/model-selector.tsx", "components/ai-elements/provider-logos.ts", "app/chat/ModelEffortPicker.tsx", "app/chat/ModelEffortPanel.tsx"]) {
    assert.doesNotMatch(tsx(file), /models\.dev\/logos|https?:\/\/[^"'`\s]*\.svg/, `${file} loads a logo from outside`);
  }
  const notices = readFileSync(new URL("../../THIRD_PARTY_NOTICES.md", import.meta.url), "utf8");
  assert.match(notices, /models\.dev/);
});

test("model sections: the server default is its own row, the rest are grouped by provider in the catalog's order, each row with its own logo, tick and flags", () => {
  const sections = modelSections(pickerCatalog, "haiku");
  assert.deepEqual(sections.defaultChoice, { value: null, checked: false, defaultName: "haiku" });
  assert.deepEqual(sections.groups.map((g) => g.provider), ["openrouter", "siliconflow", "zhipu", "custom"]);
  assert.deepEqual(sections.groups.map((g) => g.label), ["OpenRouter", "SiliconFlow", "智谱 GLM", null]);
  assert.deepEqual(sections.groups.map((g) => g.logo), ["openrouter", "siliconflow", "zhipuai", null]);
  // The same entries modelChoices keeps: the one whose key is missing is hidden unless it is the current model.
  assert.deepEqual(sections.groups[0].items.map((i) => i.value), ["haiku", "ember"]);
  assert.deepEqual(sections.groups.flatMap((g) => g.items).filter((i) => i.checked).map((i) => i.value), ["haiku"]);
  const haiku = sections.groups[0].items[0];
  assert.deepEqual([haiku.name, haiku.model, haiku.logo, haiku.thinking, haiku.keyMissing], ["Haiku 5.5", "anthropic/claude-haiku-5.5", "anthropic", true, false]);
  assert.equal(sections.groups[0].items[1].thinking, false, "unknown support draws no icon");
  const missing = modelSections(pickerCatalog, "terra");
  assert.deepEqual(missing.groups[0].items.map((i) => i.value), ["haiku", "terra", "ember"]);
  assert.equal(missing.groups[0].items[1].keyMissing, true);
  assert.equal(missing.groups[0].items[1].checked, true);
  assert.equal(modelSections(pickerCatalog, null).defaultChoice.checked, true);
  assert.deepEqual(modelSections({ default: null, models: [] }, null), { defaultChoice: { value: null, checked: true, defaultName: null }, groups: [] });
  assert.equal(providerLabel("custom"), null);
  assert.equal(providerLabel("zhipu"), "智谱 GLM");
});

test("effort words and marks: every tier has a hint, the bars and tone only rise, 默认 is neutral, the top tiers are the gradient", () => {
  for (const level of [null, ...EFFORT_LEVELS]) assert.ok(effortHint(level).length > 0, `no hint for ${level}`);
  assert.equal(effortHint(undefined), effortHint(null));
  assert.equal(effortHint("bogus"), "");
  const bars = EFFORT_LEVELS.map(effortBars);
  assert.deepEqual(bars, [...bars].sort((a, b) => a - b));
  assert.ok(bars.every((n) => n >= 0 && n <= 3));
  const tones = EFFORT_LEVELS.map(effortTone);
  assert.deepEqual(tones, [...tones].sort((a, b) => a - b));
  assert.equal(effortTone(null), 0);
  assert.equal(effortTone("none"), 0);
  assert.equal(effortTone("max"), 1);
  assert.ok(effortTone("high") > effortTone("medium"));
  assert.deepEqual(EFFORT_LEVELS.filter(effortHigh), ["xhigh", "max"]);
  assert.equal(effortHigh(null), false);
});

test("trigger view: the logo and short name of the model, the tier's word and bars; the server default has no name of its own, an unknown model shows its id", () => {
  const haiku = pickerCatalog.models[0];
  assert.deepEqual(triggerView({ model: "haiku", reasoning_effort: "high" }, haiku), { name: "Haiku 5.5", logo: "anthropic", value: "high", level: "高", bars: 3, tone: effortTone("high"), high: false });
  assert.deepEqual(triggerView({ model: null, reasoning_effort: null }, haiku), { name: null, logo: "anthropic", value: null, level: "默认", bars: 0, tone: 0, high: false });
  assert.deepEqual(triggerView({ model: "gone", reasoning_effort: "max" }, null), { name: "gone", logo: null, value: "max", level: "最高", bars: 3, tone: 1, high: true });
  assert.equal(triggerView({ model: "haiku", reasoning_effort: "none" }, haiku).bars, 0);
});

test("the selector's sources: one gradient in one place, no colour written in the components, motion respected, every phrase translated", () => {
  const css = readFileSync(new URL("../src/styles/model-picker.css", import.meta.url), "utf8");
  // The two gradient colours are named once; the only gradients of the selector are the strength's (text) and the current row's fade (soft blue to nothing).
  assert.match(css, /--effort-from:\s*var\(--accent\)/);
  assert.match(css, /--effort-to:\s*var\(--violet-600\)/);
  assert.match(css, /\[data-theme="dark"\][^{]*\{[^}]*--effort-to:\s*var\(--violet-300\)/);
  const gradients = [...css.matchAll(/linear-gradient\(([^)]*(?:\([^)]*\)[^)]*)*)\)/g)].map((m) => m[1]);
  assert.ok(gradients.every((g) => /--effort-from|--accent-soft/.test(g)), `an unexpected gradient: ${gradients.join(" | ")}`);
  for (const file of ["app/chat/ModelEffortPicker.tsx", "app/chat/ModelEffortPanel.tsx", "components/ai-elements/model-selector.tsx"]) {
    const source = tsx(file);
    assert.doesNotMatch(source, /gradient\(/, `${file} writes a gradient`);
    assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, `${file} writes a colour`);
  }
  // Reduced motion: the app's own level and the system setting both stop the bounce and the glow's fade.
  assert.match(css, /\[data-motion="off"\][^{]*\.effort-thumb[^{]*\{[^}]*transition:\s*none/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*\.effort-thumb[^}]*transition:\s*none/);
  // Every phrase the two files say is in the Chinese catalogue (and the i18n test then wants its English), and none of the catalogue's new phrases is left unused.
  const zh = JSON.parse(readFileSync(new URL("../src/locales/zh-CN.json", import.meta.url), "utf8"));
  const used = new Set();
  for (const file of ["app/chat/ModelEffortPicker.tsx", "app/chat/ModelEffortPanel.tsx"]) for (const m of tsx(file).matchAll(/\bt\("([^"]+)"\)/g)) used.add(m[1]);
  for (const phrase of used) assert.ok(zh.includes(phrase), `not in zh-CN.json: ${phrase}`);
  for (const level of [null, ...EFFORT_LEVELS]) assert.ok(zh.includes(effortHint(level)), `hint not in zh-CN.json: ${effortHint(level)}`);
  for (const level of [null, ...EFFORT_LEVELS]) assert.ok(zh.includes(effortLabel(level)), `label not in zh-CN.json: ${effortLabel(level)}`);
});

test("the selector keeps its behaviour: the server default row, 缺 key, the sentence about keys", () => {
  const panel = tsx("app/chat/ModelEffortPanel.tsx");
  assert.match(panel, /t\("服务器默认模型"\)/);
  assert.match(panel, /t\("缺 key"\)/);
  assert.match(panel, /t\("模型和 key 只在服务器上，浏览器不保存 key。"\)/);
  // Every opening starts the list's highlight on the current model (the panel stays mounted between openings).
  assert.match(panel, /useEffect\(\(\) => \{ if \(props\.open\) setHighlight\(props\.shown\.model \?\? DEFAULT_VALUE\); \}, \[props\.open, props\.shown\.model\]\)/);
  // Wide screen: the Model Selector dialog; narrow: a drawer.  Both carry a title for a screen reader.
  assert.match(panel, /<ModelSelectorContent title=\{title\}/);
  assert.match(panel, /<DrawerTitle className="sr-only">/);
  assert.match(panel, /useMatchMedia\(PHONE_QUERY\)/);
});
