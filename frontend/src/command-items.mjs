// What the command palette (Cmd-K) lists and in what order (design 4.1).  Pure: the labels come in already translated, the
// data (watch list, bots, recent conversations) is passed in; no React, no window.
//
// Four groups: 公司 (the watch list, plus "add and open" for a valid ticker that is not on it), bot (hidden ones too), 页面
// (every page of the route table the reader may open), 最近对话.  Matching is on the name the reader sees (the English one
// in the English interface), the Chinese phrase it came from, the code and the aliases; no pinyin.
import { paths } from "./routes.mjs";
import { areaItems, areaPath, needsLogin } from "./shell-nav.mjs";
import { MAX_WATCHLIST, normalizeTicker } from "./watchlist.mjs";

export const GROUP_ORDER = ["company", "bot", "page", "recent"];
export const RECENT_LIMIT = 8;

/** Names for the tickers the app itself ships with and the best-known others: a convenience for matching, never shown as data. */
const COMPANY_NAMES = {
  AAPL: ["Apple", "苹果"], MSFT: ["Microsoft", "微软"], GOOGL: ["Alphabet", "Google", "谷歌"], GOOG: ["Alphabet", "Google", "谷歌"],
  AMZN: ["Amazon", "亚马逊"], NVDA: ["NVIDIA", "英伟达"], META: ["Meta", "Facebook", "脸书"], TSLA: ["Tesla", "特斯拉"],
  AMD: ["AMD", "超威"], NFLX: ["Netflix", "奈飞"], INTC: ["Intel", "英特尔"], ORCL: ["Oracle", "甲骨文"], CRM: ["Salesforce"],
  AVGO: ["Broadcom", "博通"], TSM: ["TSMC", "台积电"], BABA: ["Alibaba", "阿里巴巴"], JPM: ["JPMorgan", "摩根大通"],
  DIS: ["Disney", "迪士尼"], KO: ["Coca-Cola", "可口可乐"], WMT: ["Walmart", "沃尔玛"], COST: ["Costco", "好市多"],
};
export const companyNames = (symbol) => COMPANY_NAMES[symbol] ?? [];

const fold = (text) => String(text ?? "").normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();

/**
 * How well `query` matches one text: 0 the whole text, 1 its start, 2 the start of a word in it, 3 somewhere inside it, -1 not at all.
 * An empty query matches everything at rank 0 (the caller shows the default list).
 */
export function matchRank(query, text) {
  const q = fold(query);
  if (!q) return 0;
  const hay = fold(text);
  if (!hay) return -1;
  if (hay === q) return 0;
  if (hay.startsWith(q)) return 1;
  if (hay.split(/[\s·.\-_/]+/).some((word) => word.startsWith(q))) return 2;
  return hay.includes(q) ? 3 : -1;
}

/** The best rank of the query over a list of texts (-1 when none matches). */
export function bestRank(query, texts) {
  let best = -1;
  for (const text of texts) {
    const rank = matchRank(query, text);
    if (rank >= 0 && (best < 0 || rank < best)) best = rank;
  }
  return best;
}

/**
 * The pages the reader may open from the palette: every page in the route table that has no parameter in its address, named by its area.
 * `t` translates a Chinese phrase.  A guest does not get the pages that need a login.
 */
export function pageItems({ personal, symbol = "AAPL", t = (text) => text }) {
  const rows = [];
  const add = (areaLabel, label, path, extra = []) => rows.push({ id: `page:${path}`, kind: "page", label: t(label), area: t(areaLabel), path, keywords: [label, areaLabel, ...extra] });
  add("对话", "对话", paths.chat());
  add("对话", "历史对话", paths.chatHistory());
  for (const item of areaItems("research", { personal })) add("研究", item.label, areaPath("research", symbol, item.id));
  add("研究", "监控状态", paths.monitor());
  add("持仓", "持仓", paths.portfolio());
  add("任务", "任务", paths.routines(), ["例行任务"]);
  for (const item of areaItems("assistant", { personal: true })) add("助手", item.label, areaPath("assistant", symbol, item.id));
  for (const item of areaItems("settings", { personal })) add("设置", item.label, areaPath("settings", symbol, item.id));
  return personal ? rows : rows.filter((row) => !needsLogin(row.path));
}

/** Bots as palette rows.  A hidden bot is listed too, marked. */
export function botItems(bots, { t = (text) => text } = {}) {
  return bots.map((bot) => ({
    id: `bot:${bot.id}`, kind: "bot", label: bot.name, path: bot.is_default ? paths.chat() : paths.chat(bot.id),
    hidden: Boolean(bot.hidden), note: bot.hidden ? t("已隐藏") : bot.title || "", keywords: [bot.name, bot.title ?? ""],
  }));
}

/** The watch list as palette rows; `locale` picks which alias is shown beside the code. */
export function companyItems(symbols, { locale = "zh-CN" } = {}) {
  return symbols.map((symbol) => {
    const [english, ...rest] = companyNames(symbol);
    const chinese = rest.find((name) => /[一-鿿]/.test(name));
    return { id: `company:${symbol}`, kind: "company", symbol, label: symbol, note: (locale === "zh-CN" ? chinese ?? english : english) ?? "", keywords: [symbol, ...companyNames(symbol)], path: paths.company(symbol) };
  });
}

/** Recent conversations as rows, newest first, as the list API returns them. */
export function recentItems(conversations, { t = (text) => text } = {}) {
  return conversations.map((conversation) => ({
    id: `recent:${conversation.id}`, kind: "recent", label: conversation.title?.trim() || t("新对话"), path: paths.chatConversation(conversation.id), keywords: [conversation.title ?? ""],
  }));
}

/** The "add and open" row for a query that is a valid ticker not on the list (and the list has room); null otherwise. */
export function addCandidate(query, symbols) {
  const ticker = normalizeTicker(query);
  if (!ticker || symbols.includes(ticker) || symbols.length >= MAX_WATCHLIST) return null;
  return { id: `add:${ticker}`, kind: "add", symbol: ticker, label: ticker, path: paths.company(ticker), keywords: [ticker] };
}

/**
 * The palette's content for one query: groups in display order, each with its rows in order.  Rows are ranked by how well they
 * match; the group holding the best row comes first, so the row the palette selects (the first one on screen) is the best match
 * and Enter does what the reader typed.  The add row ranks after prefix matches among the companies (typing "TS" selects TSLA,
 * typing "AMD" with no match offers AMD).  With no query: the groups in their default order, the recent list cut to RECENT_LIMIT.
 *
 * `sources`: { companies, bots, pages, recents, symbols } — the rows from the builders above, and the watch list's tickers.
 */
export function arrange(query, sources) {
  const q = fold(query);
  const { companies = [], bots = [], pages = [], recents = [], symbols = [] } = sources;
  const ranked = (rows) => rows.map((row, index) => ({ row, index, rank: bestRank(q, [row.label, row.note ?? "", ...(row.keywords ?? [])]) }))
    .filter((entry) => entry.rank >= 0).sort((a, b) => a.rank - b.rank || a.index - b.index);
  const groups = [];
  const company = ranked(companies);
  const add = q ? addCandidate(query, symbols) : null;
  if (add) {
    // After the prefix matches (rank <= 1), before a mere substring or word match.
    const at = company.findIndex((entry) => entry.rank > 1);
    company.splice(at < 0 ? company.length : at, 0, { row: add, index: -1, rank: 1.5 });
  }
  groups.push({ id: "company", entries: company });
  groups.push({ id: "bot", entries: ranked(bots) });
  groups.push({ id: "page", entries: ranked(pages) });
  const recent = ranked(recents);
  groups.push({ id: "recent", entries: q ? recent : recent.slice(0, RECENT_LIMIT) });
  const live = groups.filter((group) => group.entries.length);
  if (q) live.sort((a, b) => a.entries[0].rank - b.entries[0].rank || GROUP_ORDER.indexOf(a.id) - GROUP_ORDER.indexOf(b.id));
  return live.map((group) => ({ id: group.id, rows: group.entries.map((entry) => entry.row) }));
}
