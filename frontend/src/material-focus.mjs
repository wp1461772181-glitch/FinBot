// 资料库 links and scope (UX batch 2, P1).  A confirmed agent save replies with
// #materials?symbol=AAPL&focus=<uploaded_media id>; opening it lands on that row.
// The workspace card also links SEC filings, so it adds &type=official_filing.
/** The 工作区 card's link to one 资料库 row; its type keeps an SEC filing from being looked for among uploads. */
export function materialHref(symbol, item) {
  return `#materials?symbol=${encodeURIComponent(symbol)}&focus=${item.source_id}&type=${item.source_type}`;
}

/** The symbol the library request filters on: none for 全部股票. */
export function librarySymbol(scope, symbol) {
  return scope === "all" ? "" : symbol;
}

/** A stored focus is usable when it names a material; an analysis id is optional (a fresh save has none). */
export function usableFocus(value, symbol) {
  if (!value || typeof value !== "object") return null;
  if (value.symbol !== symbol) return null;
  if (value.source_type !== "official_filing" && value.source_type !== "uploaded_media") return null;
  if (typeof value.source_id !== "string" || !value.source_id) return null;
  return { symbol, source_type: value.source_type, source_id: value.source_id,
           analysis_id: typeof value.analysis_id === "string" ? value.analysis_id : null };
}
