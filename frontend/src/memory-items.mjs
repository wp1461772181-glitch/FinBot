import { dayLabel } from "./owner-views.mjs";
import { templateLabel } from "./role-templates.mjs";

// Pure helpers of the memory page (profile items and past conversations), kept apart so node tests read them.

const ORIGIN_LABELS = { explicit: "你说的", inferred: "推断", manual: "你写的", pattern: "你确认的推测" };
const RECALL_KIND_LABELS = { summary: "摘要", questions: "你的提问" };

export function originLabel(origin) { return ORIGIN_LABELS[origin] ?? origin; }
export function recallKindLabel(kind) { return RECALL_KIND_LABELS[kind] ?? kind; }

/** Active items first (the owner's own — said or typed — then inferred; oldest first, the order the model
 *  sees), archived apart. */
export function profileGroups(items) {
  const rank = item => (item.origin === "inferred" ? 1 : 0);
  const byAge = (a, b) => rank(a) - rank(b) || String(a.created_at ?? "").localeCompare(String(b.created_at ?? ""));
  const list = Array.isArray(items) ? items : [];
  return { active: list.filter(i => i.status === "active").sort(byAge), archived: list.filter(i => i.status !== "active" && i.status !== "proposed").sort(byAge) };
}

/** True for a confirmed guess the quarterly settle made long-term (the page tags it 「长期」). */
export function isSettled(item) { return Boolean(item?.settled_at); }

/** The quiet line 「最近一次印证：M月D日」 (English: "Last borne out: M/D"); "" when the item has no last_seen_at. */
export function seenLine(item, locale = "zh-CN") {
  const day = dayLabel(item?.last_seen_at, locale);
  if (!day) return "";
  return locale === "en-US" ? `Last borne out: ${day}` : `最近一次印证：${day}`;
}

/**
 * An item that came from a role template (4f) says so: a badge 「模板·短线」 and, where the quote of his own words would be, the line 「你在 M月D日 选用模板「短线」时加的」 (the quote of
 * such an item is the template's own text, not something he said).  `null` for any other item, which then shows exactly what it showed before.  The label is the server's `template_label`.
 */
export function templateNote(item, locale = "zh-CN") {
  if (!item?.template) return null;
  const label = templateLabel(item.template_label, locale);
  const day = dayLabel(item.created_at, locale);
  if (locale === "en-US") {
    return { badge: label ? `Template · ${label}` : "Template", line: `Added${day ? ` on ${day}` : ""} when you picked the template${label ? ` "${label}"` : ""}` };
  }
  return { badge: label ? `模板·${label}` : "模板", line: `你${day ? `在 ${day} ` : ""}选用模板${label ? `「${label}」` : ""}时加的` };
}

/** The archived row's own line: the reason the settle gave, and the day it was set aside (「M月D日 归档」 / "archived M/D"); either may be missing. */
export function archiveNote(item, locale = "zh-CN") {
  const day = dayLabel(item?.archived_at, locale);
  return { reason: String(item?.archived_reason ?? "").trim(), date: day ? (locale === "en-US" ? `archived ${day}` : `${day} 归档`) : "" };
}

/** The monthly review's guesses waiting for his answer (status proposed), newest first.  Rejected ones never come from the server. */
export function proposedItems(items) {
  const list = Array.isArray(items) ? items : [];
  return list.filter(i => i.status === "proposed").sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
}

/** The quoted sentences of a guess, each with a short date; rows without a quote are dropped. */
export function exampleLines(item) {
  const rows = Array.isArray(item?.examples) ? item.examples : [];
  return rows.filter(e => e && String(e.quote ?? "").trim()).map((e, n) => ({ key: String(e.message_id ?? n), quote: String(e.quote).trim(), date: String(e.date ?? "").slice(0, 10) }));
}

/** Active profile items by layer: 全局 first, then each bot (the default bot first, in the order given),
 *  then items of bots that no longer exist.  Empty layers are kept for bots so the page can name them. */
export function profileLayers(items, bots) {
  const list = Array.isArray(items) ? items : [];
  const known = Array.isArray(bots) ? [...bots].sort((a, b) => Number(Boolean(b.is_default)) - Number(Boolean(a.is_default))) : [];
  const { active } = profileGroups(list);
  const layers = [{ key: "global", label: "全局", bot: null, items: active.filter(i => !i.bot_id) }];
  for (const bot of known) layers.push({ key: bot.id, label: bot.name, bot, items: active.filter(i => i.bot_id === bot.id) });
  const ids = new Set(known.map(b => b.id));
  const orphans = active.filter(i => i.bot_id && !ids.has(i.bot_id));
  if (orphans.length) layers.push({ key: "gone", label: "已删除的 bot", bot: null, items: orphans });
  return layers;
}

/** The fields of a typed item (memory page ＋ 添加), or an error phrase.  ``layer`` "" is 全局. */
export function manualItemDraft({ kind, text, layer } = {}) {
  const clean = String(text ?? "").split(/\s+/).filter(Boolean).join(" ");
  if (!clean) return { error: "先写下要记住的内容。" };
  if (clean.length > 200) return { error: "最多 200 个字。" };
  if (!["preference", "about_me", "instruction", "style", "recent"].includes(kind)) return { error: "请选择类型。" };
  return { fields: { kind, text: clean, bot_id: layer ? String(layer) : null } };
}

/** Where an item lives, as a label: 全局 or the bot's name. */
export function layerLabel(item) { return item?.bot_id ? (item.bot_name || "已删除的 bot") : "全局"; }

/** Past conversations grouped by bot, in first-seen order (the list is newest first). */
export function recallGroups(items) {
  const groups = new Map();
  for (const item of Array.isArray(items) ? items : []) {
    const key = item.bot_id ?? "none";
    if (!groups.has(key)) groups.set(key, { key, label: item.bot_name || (item.bot_id ? "已删除的 bot" : "未归属"), items: [] });
    groups.get(key).items.push(item);
  }
  return [...groups.values()];
}

/** What a refused 恢复 says.  409 is "full" only when the server's detail is `profile_full`; any other 409 carries the server's own Chinese
 *  reason (a same-topic or same-text item is already in use), shown as given. */
export function restoreFailText(status, detail) {
  if (status === 404) return "这条已不存在。";
  if (status === 409) {
    if (detail === "profile_full") return "这一层的记忆已满，先删掉一条再恢复。";
    if (typeof detail === "string" && /[\u4e00-\u9fff]/.test(detail)) return detail;
  }
  return "恢复失败，请重试。";
}
