// The chat badge's quick select (model + reasoning effort per bot): pure state mapping, no React here.
// Tiers are the provider's own set (OpenRouter reasoning.effort, agent_chat_provider.REASONING_EFFORTS);
// the list is checked against the server in scripts/model-effort.test.mjs.  Nothing is ever disabled: a
// model that ignores a tier simply ignores it, and the owner decides.

export const EFFORT_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];
const EFFORT_LABELS = { none: "无", minimal: "极简", low: "低", medium: "中", high: "高", xhigh: "极高", max: "最高" };

/** The Chinese label of an effort value; null/undefined is the default (nothing sent). */
export function effortLabel(value) {
  if (value === null || value === undefined) return "默认";
  return EFFORT_LABELS[value] ?? String(value);
}

/**
 * The catalog entry a bot's badge is about: the bot's own model, or the server default when the bot names none.
 * null when no entry can be found (the strength list then falls back to every tier).
 */
export function effectiveEntry(catalog, model) {
  if (!catalog) return null;
  const name = model ?? catalog.default ?? null;
  return name === null ? null : catalog.models.find((entry) => entry.name === name) ?? null;
}

/**
 * The strength tiers a model takes, from what the catalog says about it (OpenRouter's reasoning block):
 * reasoning_supported false means it takes no effort at all; a supported_efforts list means only those tiers;
 * null or missing fields (unknown) mean every tier, in the display order below.
 */
export function effortSupport(entry) {
  if (entry?.reasoning_supported === false) return { reasoning: false, levels: [] };
  const declared = entry?.supported_efforts;
  if (Array.isArray(declared)) {
    const levels = EFFORT_LEVELS.filter((level) => declared.includes(level));
    return { reasoning: levels.length > 0, levels };
  }
  return { reasoning: true, levels: EFFORT_LEVELS };
}

/** True when the model takes no reasoning effort, so only 默认 is offered and the panel says so. */
export function noEffort(entry) {
  return !effortSupport(entry).reasoning;
}

/**
 * 默认 first (null: no setting), then the tiers the model takes (every tier when unknown); exactly the current one
 * is ticked.  A stored value the model does not take is kept at the top, ticked and marked, so the owner sees what
 * is stored; choosing any other row saves over it.
 */
export function effortChoices(current, entry = null) {
  const now = current ?? null;
  const { levels } = effortSupport(entry);
  const choices = [null, ...levels].map((value) => ({ value, label: effortLabel(value), checked: value === now, disabled: false }));
  if (now !== null && !levels.includes(now)) {
    choices.unshift({ value: now, label: effortLabel(now), checked: true, disabled: false, unsupported: true });
  }
  return choices;
}

/**
 * 服务器默认 first, then the catalog entries whose key is configured.  A current model whose key is missing
 * is still listed (marked keyMissing) so the owner can see what the bot is set to.
 */
export function modelChoices(catalog, current) {
  const now = current ?? null;
  const choices = [{ value: null, label: `服务器默认模型${catalog.default ? ` (${catalog.default})` : ""}`, checked: now === null }];
  for (const entry of catalog.models) {
    const configured = entry.key_status === "configured";
    if (!configured && entry.name !== now) continue;
    choices.push({ value: entry.name, label: `${entry.display_name} · ${entry.model}`, checked: entry.name === now, ...(configured ? {} : { keyMissing: true }) });
  }
  return choices;
}

/** A save sends only the field the owner changed. */
export function patchFor(kind, value) {
  return kind === "model" ? { model: value ?? null } : { reasoning_effort: value ?? null };
}

/** The badge text: 模型 · {model} · {effort label}.  `t` translates the fixed words (the page passes its i18n). */
export function badgeText(bot, t = (text) => text) {
  const model = bot.model ? bot.model : t("服务器默认模型");
  return `${t("模型")} · ${model} · ${t(effortLabel(bot.reasoning_effort))}`;
}

// ---- The picker's own view of the catalog (the composer's model selector): logos, provider groups, the trigger's parts.
// Pure state mapping as above; nothing here changes what a choice saves.

/** Logo files shipped with the app (src/assets/provider-logos/<key>.svg); "generic" is the stand-in for any provider without one. */
export const LOGO_KEYS = ["anthropic", "openai", "google", "xai", "mistral", "groq", "deepseek", "openrouter", "moonshotai", "alibaba", "zhipuai", "siliconflow", "minimax", "meta", "nvidia", "perplexity", "cohere"];

// The catalog's own provider names (app/agent_chat_api.py PROVIDER_NAMES) plus the first-party names a hand-written catalog file may use.
const PROVIDER_LOGO = { deepseek: "deepseek", kimi: "moonshotai", moonshotai: "moonshotai", qwen: "alibaba", alibaba: "alibaba", zhipu: "zhipuai", zhipuai: "zhipuai", minimax: "minimax",
  siliconflow: "siliconflow", openrouter: "openrouter", anthropic: "anthropic", openai: "openai", google: "google", xai: "xai", mistral: "mistral", groq: "groq" };
// The vendor prefix of an OpenRouter model id (`anthropic/claude-…`); OpenRouter's own spellings differ from the logo keys in a few places.
const VENDOR_LOGO = { anthropic: "anthropic", openai: "openai", google: "google", "x-ai": "xai", xai: "xai", mistralai: "mistral", mistral: "mistral", deepseek: "deepseek", "deepseek-ai": "deepseek",
  moonshotai: "moonshotai", qwen: "alibaba", alibaba: "alibaba", "z-ai": "zhipuai", zhipuai: "zhipuai", "meta-llama": "meta", meta: "meta", minimax: "minimax", nvidia: "nvidia", perplexity: "perplexity", cohere: "cohere", groq: "groq" };
const PROVIDER_LABELS = { deepseek: "DeepSeek", kimi: "Kimi", moonshotai: "Kimi", minimax: "MiniMax", qwen: "通义千问", alibaba: "通义千问", zhipu: "智谱 GLM", zhipuai: "智谱 GLM", doubao: "豆包", hunyuan: "腾讯混元",
  baidu: "百度千帆", siliconflow: "SiliconFlow", openrouter: "OpenRouter", anthropic: "Anthropic", openai: "OpenAI", google: "Google", xai: "xAI", mistral: "Mistral", groq: "Groq" };

/** The logo of a provider group (null: none, the generic mark is drawn). */
export function providerLogo(provider) {
  return PROVIDER_LOGO[String(provider ?? "").toLowerCase()] ?? null;
}

/** The logo of one catalog entry: an OpenRouter entry shows its model's vendor (by the id's prefix), any other the provider's own; null when there is none (the generic mark is drawn). */
export function entryLogo(entry) {
  if (!entry) return null;
  if (String(entry.provider ?? "").toLowerCase() === "openrouter") {
    const vendor = String(entry.model ?? "").split("/")[0].replace(/^~/, "").toLowerCase();
    return VENDOR_LOGO[vendor] ?? null;
  }
  return providerLogo(entry.provider);
}

/** The group heading of a provider: its brand name (null for the catalog's own "custom" and an unknown one: the caller says 自定义 / 其他). */
export function providerLabel(provider) {
  return PROVIDER_LABELS[String(provider ?? "").toLowerCase()] ?? null;
}

/**
 * The model list of the selector: the server-default row first, then the entries modelChoices keeps (configured, or the current one), grouped by provider
 * in the order the catalog lists them.  Each row carries what the old flat list had (value, checked, keyMissing) plus the entry's own words for a richer row.
 */
export function modelSections(catalog, current) {
  const choices = modelChoices(catalog, current);
  const byName = new Map(catalog.models.map((entry) => [entry.name, entry]));
  const groups = [];
  for (const choice of choices.slice(1)) {
    const entry = byName.get(choice.value);
    const provider = String(entry?.provider ?? "");
    let group = groups.find((item) => item.provider === provider);
    if (!group) { group = { provider, label: providerLabel(provider), logo: providerLogo(provider), items: [] }; groups.push(group); }
    group.items.push({ value: choice.value, name: entry?.display_name || choice.value, model: entry?.model ?? "", logo: entryLogo(entry), checked: choice.checked,
      keyMissing: Boolean(choice.keyMissing), thinking: entry?.reasoning_supported === true });
  }
  return { defaultChoice: { value: null, checked: choices[0].checked, defaultName: catalog.default ?? null }, groups };
}

const EFFORT_HINTS = { none: "不思考，直接回答", minimal: "几乎不思考，最快", low: "快，适合简单问答", medium: "均衡，多数问题够用", high: "更细致，慢一些、贵一些",
  xhigh: "深入推理，明显更慢更贵", max: "最深的推理，最慢最贵" };
/** One line on what a tier means (Chinese; the page translates it).  null/undefined is the default. */
export function effortHint(value) {
  if (value === null || value === undefined) return "不指定，用模型自己的设置";
  return EFFORT_HINTS[value] ?? "";
}

const BARS = { none: 0, minimal: 1, low: 1, medium: 2, high: 3, xhigh: 3, max: 3 };
/** How many of the three small bars are filled for a tier (the default and an unknown value: none, and no bars are drawn for the default). */
export function effortBars(value) {
  return BARS[value] ?? 0;
}

/** 0..1: how strong the tier is, for the glow's colour (blue towards violet).  The default and "none" are 0; "max" is 1. */
export function effortTone(value) {
  const at = EFFORT_LEVELS.indexOf(value);
  return at <= 0 ? 0 : Math.round((at / (EFFORT_LEVELS.length - 1)) * 100) / 100;
}

/** True for the top tiers, where the label is drawn in the gradient. */
export function effortHigh(value) {
  return value === "xhigh" || value === "max";
}

/** What the composer's button shows: the model's logo and short name (null name: the server default), the tier label and its bars.  `entry` is effectiveEntry(...). */
export function triggerView(bot, entry) {
  const value = bot.reasoning_effort ?? null;
  return { name: bot.model ? (entry?.display_name || bot.model) : null, logo: entryLogo(entry), value, level: effortLabel(value), bars: value === null ? 0 : effortBars(value), tone: effortTone(value), high: effortHigh(value) };
}
