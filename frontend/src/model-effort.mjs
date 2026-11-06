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

/** 默认 first (null: no setting), then every tier; exactly the current one is ticked. */
export function effortChoices(current) {
  const now = current ?? null;
  return [null, ...EFFORT_LEVELS].map((value) => ({ value, label: effortLabel(value), checked: value === now, disabled: false }));
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
