import { Navigate, useParams } from "react-router";
import { EmptyState } from "@/components/state/EmptyState";
import { translatePhrase } from "../../i18n";
import { paths, symbolParam } from "../../routes.mjs";
import { normalizeTicker } from "../../watchlist.mjs";
import { DEFAULT_SYMBOL, DEFAULT_SYMBOLS } from "../WorkspaceLayout";
import { useWorkspace } from "../workspace";

/** What a research page shows when the watchlist is empty (the pages that start from a company: the replay page): the notice, and one way out, putting the default stocks back. */
export function EmptyWatchlist() {
  const ws = useWorkspace();
  return <main className="mx-auto flex w-full max-w-[1120px] flex-1 flex-col p-4 lg:p-6">
    <EmptyState title={translatePhrase("关注列表为空")} description={translatePhrase("添加一只股票，或恢复默认关注股票，继续查看研究总览。")}
      action={{ label: translatePhrase("恢复默认股票"), onClick: () => { ws.setSymbols(DEFAULT_SYMBOLS); ws.setPreferredSymbol(DEFAULT_SYMBOL); } }} />
  </main>;
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
