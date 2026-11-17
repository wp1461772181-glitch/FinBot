import { Navigate, useParams } from "react-router";
import { translatePhrase } from "../../i18n";
import { paths, symbolParam } from "../../routes.mjs";
import { normalizeTicker } from "../../watchlist.mjs";
import { DEFAULT_SYMBOL, DEFAULT_SYMBOLS } from "../WorkspaceLayout";
import { useWorkspace } from "../workspace";

/** What a research page shows when the watchlist is empty (the pages that start from a company: the replay page). */
export function EmptyWatchlist() {
  const ws = useWorkspace();
  return <main className="workspace"><section className="empty-watchlist"><h1>{translatePhrase("关注列表为空")}</h1><p>{translatePhrase("添加一只股票，或恢复默认关注股票，继续查看研究总览。")}</p><button className="primary-action" onClick={() => { ws.setSymbols(DEFAULT_SYMBOLS); ws.setPreferredSymbol(DEFAULT_SYMBOL); }}>{translatePhrase("恢复默认股票")}</button></section></main>;
}

/** A record id from the address, or a redirect to the forecast home (an unreadable address never guesses at a record). */
export function useRecordParam(name: string): string | null {
  const value = useParams()[name] ?? "";
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) ? value.toLowerCase() : null;
}

export function ToForecastHome() { return <Navigate to={paths.forecasts()} replace />; }

/** The company an address names, validated; null when it is not a ticker. */
export function useCompanyParam(): string | null {
  const raw = useParams().symbol ?? "";
  return normalizeTicker(symbolParam(raw));
}
