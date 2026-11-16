// The one check of a code the reader adds to the watchlist (the research bar's field, the watchlist page's field, the company page's ★): the code to add, or the
// sentence (a zh-CN phrase key) that says why not.  The three sentences are the ones the research bar has always shown.
import { MAX_WATCHLIST, normalizeTicker } from "./watchlist.mjs";

export function checkWatchAdd(raw, symbols) {
  const ticker = normalizeTicker(raw);
  if (!ticker) return { ok: false, error: "请输入有效的美股代码，例如 AMD 或 BRK.B。" };
  if (symbols.includes(ticker)) return { ok: false, error: "该代码已在关注列表中。" };
  if (symbols.length >= MAX_WATCHLIST) return { ok: false, error: `关注列表最多保存 ${MAX_WATCHLIST} 个代码。` };
  return { ok: true, ticker };
}
