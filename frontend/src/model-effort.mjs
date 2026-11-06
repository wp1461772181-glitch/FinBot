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
