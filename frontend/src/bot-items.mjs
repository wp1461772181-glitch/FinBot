// Pure helpers of the bot sidebar (personal agent, second edition), kept apart so node tests read them.  The helpers of the bot's profile form and of the
// new-bot dialog are in bot-form-items.mjs (P5.1): this file is on the first screen (the sidebar reads it), so nothing only the settings page needs stays here.
// They are re-exported below so that every older import and its test read what they always read.

const BOT_LINK = /^#bot\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

/** The bot id of a bot link (#bot/<id>), else null. */
export function botFromHash(hash) { const match = BOT_LINK.exec(String(hash ?? "")); return match ? match[1].toLowerCase() : null; }

/** The sidebar: the default bot alone on top, then the owner's groups (ungrouped first, then by name); pinned
 * first inside each, then the most recently active, then by name.  Hidden bots are left out unless asked for. */
export function botSections(bots, { showHidden = false } = {}) {
  const list = (Array.isArray(bots) ? bots : []).filter(b => showHidden || !b.hidden || b.is_default);
  const top = list.find(b => b.is_default) ?? null;
  const rest = list.filter(b => b !== top).sort((a, b) =>
    Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || String(b.last_at ?? "").localeCompare(String(a.last_at ?? "")) || a.name.localeCompare(b.name));
  const groups = new Map();
  for (const bot of rest) { const key = (bot.group ?? "").trim(); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(bot); }
  const names = [...groups.keys()].sort((a, b) => (a === "" ? -1 : b === "" ? 1 : a.localeCompare(b)));
  return { top, groups: names.map(name => ({ name, bots: groups.get(name) })) };
}

export { MAX_FOCUS_COMPANIES, botDraft, newBotFields, toggleTool, toolEnabled, parseFocusSymbols, focusText, keyStatusLabel, botModelLabel } from "./bot-form-items.mjs";
