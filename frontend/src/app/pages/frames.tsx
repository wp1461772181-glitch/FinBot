import type { ReactNode } from "react";
import { Navigate, useParams } from "react-router";
import type { ResearchSection } from "../../workspace-sections.mjs";
import { WorkspacePageHeader, isSupportedSymbol } from "../../OverviewWorkspace";
import { translatePhrase } from "../../i18n";
import { paths, symbolParam } from "../../routes.mjs";
import { normalizeTicker } from "../../watchlist.mjs";
import { DEFAULT_SYMBOL, DEFAULT_SYMBOLS } from "../WorkspaceLayout";
import { useWorkspace } from "../workspace";

/** The old research pages' frame: header, section tabs, then the page.  With an empty queue the pages that read it show this notice instead. */
export function ResearchFrame({ section, children }: { section: ResearchSection; children: ReactNode }) {
  const ws = useWorkspace();
  if (!ws.symbols.length) return <EmptyWatchlist />;
  return <main className="workspace" aria-labelledby="workspace-title">
    <WorkspacePageHeader symbol={ws.symbol} section={section} recordCount={null} supported={isSupportedSymbol(ws.symbol)} />
    {children}
  </main>;
}

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
