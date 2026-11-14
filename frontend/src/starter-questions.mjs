// The three questions an empty line offers (design 4.2, 空).  Clicking one fills the composer; it never sends.  Each has the Chinese `phrase`
// (the key in the catalog, with {symbol} where a company goes) and `text`, the phrase with the company put in.

const withSymbol = (symbol, phrases) => phrases.map((phrase, index) => ({ id: `company-${index + 1}`, phrase, symbol, text: phrase.replace("{symbol}", symbol) }));
const plain = (id, phrases) => phrases.map((phrase, index) => ({ id: `${id}-${index + 1}`, phrase, symbol: null, text: phrase }));

const COMPANY = ["查看 {symbol} 最近行情", "{symbol} 已保存的最新财报有哪些", "{symbol} 最新的预测是什么"];
const NEWS = ["今天有哪些要闻？", "关注列表里的公司今天有什么新闻？", "最近一周有哪些值得注意的新闻？"];
const EARNINGS = ["解读最近一期财报", "最近一期财报里有哪些风险因素？", "最近一期财报的收入和利润有什么变化？"];
const GENERAL = ["关注列表里的公司最近行情怎么样？", "最近有哪些公司发布了新的财报？", "可信度星级是什么"];

/** The company a bot is about: the first one it watches, else its default company; null when it has none. */
export function botSymbol(bot) {
  const watched = bot?.focus?.companies?.find((company) => typeof company?.symbol === "string" && company.symbol.trim());
  const symbol = watched?.symbol ?? bot?.default_company?.symbol;
  return typeof symbol === "string" && symbol.trim() ? symbol.trim().toUpperCase() : null;
}

/** Three starters for a bot: its company's quote, latest filing and latest forecast; today's news; the latest earnings read; or general ones that name no company. */
export function starterQuestions(bot) {
  const symbol = botSymbol(bot);
  if (symbol) return withSymbol(symbol, COMPANY);
  if (bot?.template === "news_monitor") return plain("news", NEWS);
  if (bot?.template === "earnings_reader") return plain("earnings", EARNINGS);
  return plain("general", GENERAL);
}

/** Every phrase this module can produce (the catalog test reads it). */
export const STARTER_PHRASES = [...COMPANY, ...NEWS, ...EARNINGS, ...GENERAL];
