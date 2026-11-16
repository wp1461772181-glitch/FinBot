import { ApiError } from "../../api/base";
import { translatePhrase } from "../../i18n";
import type { SupportedSymbol } from "../../workspace-sections.mjs";

/** Whether a code looks like a US ticker the app can start research on (SEC scans and new forecasts need one). */
export function isSupportedSymbol(symbol: string): symbol is SupportedSymbol {
  return /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/i.test(symbol.trim());
}

/** Titles that carry a code are written whole in each language (a phrase catalog cannot hold a sentence with a hole in it). */
export const removeTitle = (symbol: string, locale: string) => locale === "en-US" ? `Remove ${symbol} from the watchlist?` : `从自选移出 ${symbol}？`;
export const removeLabel = (symbol: string, locale: string) => locale === "en-US" ? `Remove ${symbol} from the watchlist` : `从自选移出 ${symbol}`;

/** What to tell the reader about a failed request: the server's own sentence for an API error, else the fallback (a zh-CN phrase key). */
export function actionMessage(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return translatePhrase(fallback);
  if (error.message.includes("SEC_EDGAR_USER_AGENT")) return translatePhrase("尚未配置 SEC 联系邮箱。请先按 README 配置后重试。");
  return translatePhrase(error.message);
}
