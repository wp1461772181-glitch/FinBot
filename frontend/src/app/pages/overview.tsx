import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { Navigate, useSearchParams } from "react-router";
import { CurrentOverviewWorkspace, Loading, WorkspacePageHeader, actionMessage, isSupportedSymbol, type FilingState } from "../../OverviewWorkspace";
import { getFilingInventory, getV2Prices } from "../../api";
import { companyTab, paths } from "../../routes.mjs";
import type { PriceHistory } from "../../types";
import { EmptyWatchlist, useCompanyParam } from "./frames";
import { useWorkspace } from "../workspace";

const ForecastsPage = lazy(() => import("./forecasts").then(m => ({ default: m.ForecastsPage })));
const MaterialsPage = lazy(() => import("./materials").then(m => ({ default: m.MaterialsPage })));

type Active = { kind: "loading"; symbol: string } | { kind: "ready"; symbol: string; filings: FilingState; priceHistory: PriceHistory | null; priceError: string | null };

/** The research overview of the company the address names (the preferred one on the bare /research). */
function Overview() {
  const ws = useWorkspace();
  const symbol = ws.symbol;
  const [retryKey, setRetryKey] = useState(0);
  const [active, setActive] = useState<Active>({ kind: "loading", symbol });
  const version = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    const current = ++version.current;
    setActive({ kind: "loading", symbol });
    Promise.allSettled([getFilingInventory(symbol, controller.signal), getV2Prices(symbol, controller.signal)]).then(([filingResult, pricesResult]) => {
      if (controller.signal.aborted || current !== version.current) return;
      const filings: FilingState = filingResult.status === "fulfilled"
        ? { kind: "ready", data: filingResult.value }
        : { kind: "error", message: actionMessage(filingResult.reason, "暂时无法读取官方申报清单。") };
      setActive({
        kind: "ready", symbol, filings,
        priceHistory: pricesResult.status === "fulfilled" ? pricesResult.value.price_history : null,
        priceError: pricesResult.status === "rejected" ? actionMessage(pricesResult.reason, "行情暂不可用。") : null,
      });
    });
    return () => controller.abort();
  }, [symbol, retryKey]);
  if (!ws.symbols.length) return <EmptyWatchlist />;
  if (active.kind === "loading" || active.symbol !== symbol) return <Loading symbol={symbol} />;
  return <main className="workspace" aria-labelledby="workspace-title">
    <WorkspacePageHeader symbol={symbol} section="overview" recordCount={null} supported={isSupportedSymbol(symbol)} />
        <CurrentOverviewWorkspace symbols={ws.symbols} personal={ws.personal} onRemove={ws.removeWatchSymbol} symbol={symbol} currentFilings={active.filings} priceHistory={active.priceHistory} priceError={active.priceError}
      onNavigate={ws.go} onOpenStock={ticker => ws.openCompany(ticker)} onPricesInitialized={() => setRetryKey(value => value + 1)} />
  </main>;
}

/** /research: the overview, still the single page it was (P6.1 splits it into the watchlist and the company page). */
export function ResearchRoute() { return <Overview />; }

/** /research/c/:symbol, ?tab=overview|forecasts|materials: one company; the tabs show the existing pages scoped to it. */
export function CompanyRoute() {
  const symbol = useCompanyParam();
  const [params] = useSearchParams();
  if (!symbol) return <Navigate to={paths.research()} replace />;
  const tab = companyTab(params);
  if (tab === "forecasts") return <Suspense fallback={null}><ForecastsPage symbolFilter={symbol} /></Suspense>;
  if (tab === "materials") return <Suspense fallback={null}><MaterialsPage symbol={symbol} focus={null} /></Suspense>;
  return <Overview />;
}
