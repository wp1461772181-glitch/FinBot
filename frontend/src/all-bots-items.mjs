// Pure helpers of the 全部 bot page (P5.2, design 4.11): the order of the cards, when a bot was last active, and the status mark of a card.
import { botSections } from "./bot-items.mjs";
import { botMarker, isWaiting } from "./bot-marker.mjs";

const flat = (sections) => [sections.top, ...sections.groups.flatMap(group => group.bots)].filter(Boolean);

/**
 * Every bot in the order of the sidebar (the default bot first, then the owner's groups, pinned first, then the most recently active, then by name:
 * bot-items.botSections), and the hidden ones after them as a last group, in the same order among themselves.  The default bot can not be hidden,
 * so it always leads.
 */
export function orderAllBots(bots) {
  const list = Array.isArray(bots) ? bots : [];
  const shown = list.filter(bot => !bot.hidden || bot.is_default), hidden = list.filter(bot => bot.hidden && !bot.is_default);
  return [...flat(botSections(shown)), ...flat(botSections(hidden, { showHidden: true }))];
}

const MINUTE = 60e3, HOUR = 60 * MINUTE, DAY = 24 * HOUR;

/**
 * How long ago a time was, as the pieces Intl.RelativeTimeFormat takes: `{ unit, value }` with a negative value (past).  null for no time or one that does
 * not read; `{ now: true }` inside the first minute (and for a time a little ahead of this clock: two devices never agree to the second).
 */
export function agoParts(iso, nowMs) {
  const at = typeof iso === "string" ? Date.parse(iso) : NaN;
  if (!Number.isFinite(at) || !Number.isFinite(nowMs)) return null;
  const age = nowMs - at;
  if (age < MINUTE) return { now: true };
  if (age < HOUR) return { unit: "minute", value: -Math.floor(age / MINUTE) };
  if (age < DAY) return { unit: "hour", value: -Math.floor(age / HOUR) };
  if (age < 30 * DAY) return { unit: "day", value: -Math.floor(age / DAY) };
  if (age < 365 * DAY) return { unit: "month", value: -Math.floor(age / (30 * DAY)) };
  return { unit: "year", value: -Math.floor(age / (365 * DAY)) };
}

/** The status mark a card's avatar draws (the sidebar's rows draw the same one): answering > waiting > unread > idle, and the unread count. */
export function cardStatus(bot, lineStatus = {}) {
  const key = `bot:${bot?.id}`;
  const marker = botMarker({ running: (lineStatus.running ?? []).includes(key), waiting: isWaiting(bot, lineStatus.waiting ?? []),
    unread: (bot?.unread > 0 ? bot.unread : 0) + ((lineStatus.unseen ?? []).includes(key) ? 1 : 0) });
  return { status: marker.kind === "running" ? "answering" : marker.kind === "waiting" ? "waiting" : marker.kind === "unread" ? "unread" : "idle", word: marker.word, count: marker.count };
}

/** The model a card names: the bot's own (the catalog's display name when it is known), or null when it has none and the catalog's default applies. */
export function cardModel(bot, catalog) {
  if (!bot?.model) return null;
  const entry = (catalog?.models ?? []).find(model => model.name === bot.model);
  return entry?.display_name || bot.model;
}
