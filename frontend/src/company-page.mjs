// The company page's small decisions as pure functions (P6.1): its name, which bots "ask a bot" lists, how a question about the company
// is handed to a bot's line, and when the page has nothing at all to show.
import { companyNames } from "./command-items.mjs";
import { lineKey, loadDraft, saveDraft } from "./chat-lines.mjs";
import { storeBotSymbol } from "./workspace-cards.mjs";

/**
 * The company's name where the app already has one: a bot's default company, a bot's focus entry, else the short trade name from the
 * matching table (a convenience for matching, see command-items.mjs).  null when none knows it; the page then shows the code alone.
 */
export function companyName(symbol, bots = []) {
  for (const bot of Array.isArray(bots) ? bots : []) {
    if (bot?.default_company?.symbol === symbol && bot.default_company.company) return bot.default_company.company;
    const focus = (bot?.focus?.companies ?? []).find((company) => company?.symbol === symbol);
    if (focus?.name) return focus.name;
  }
  return companyNames(symbol)[0] ?? null;
}

/**
 * The bots the 问 bot menu lists for a company: those whose focus names it (hidden bots are not offered, as in the sidebar), else only
 * the default bot.  `following` says which of the two it is.
 */
export function askBots(symbol, bots = []) {
  const all = Array.isArray(bots) ? bots : [];
  const following = all.filter((bot) => !bot.hidden && (bot.focus?.companies ?? []).some((company) => company?.symbol === symbol));
  if (following.length) return { bots: following, following: true };
  const fallback = all.find((bot) => bot.is_default);
  return { bots: fallback ? [fallback] : [], following: false };
}

/**
 * Hand a company to a bot's line before the page jumps there: the company becomes that bot's current stock (the key its workspace card
 * already reads), and the line's draft starts with `draftText` when the draft is empty.  Nothing is sent, and a draft the reader has
 * already typed is never touched.  Returns whether the draft was filled and which line it is.
 */
export function prepareAsk({ bot, symbol, draftText, storage = globalThis.localStorage }) {
  storeBotSymbol(bot.id, symbol, storage);
  const line = lineKey(bot, null);
  if (loadDraft(line, storage).trim()) return { prefilled: false, line };
  saveDraft(line, draftText, storage);
  return { prefilled: true, line };
}

/** The draft a question about a company starts with: "关于 AAPL：" (the page passes its locale's word and colon). */
export function askDraft(symbol, { about = "关于", colon = "：" } = {}) {
  return `${about} ${symbol}${colon}`;
}

/**
 * True when every read of the company came back and none holds anything: no candles, no forecast, no material, no filing.  A read that
 * failed or has not finished is not "nothing" (the page never says empty on a guess).
 */
export function companyIsEmpty({ prices, forecasts, materials, filings }) {
  const counts = [prices, forecasts, materials, filings];
  return counts.every((count) => Number.isFinite(count) && count === 0);
}
