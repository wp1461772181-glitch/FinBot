import { useParams } from "react-router";
import { CompanyPage, CompanyUnknown } from "../research/CompanyPage";
import { WatchlistPage } from "../research/WatchlistPage";
import { useCompanyParam } from "./frames";

/** /research: the watchlist (design 4.5). */
export function ResearchRoute() { return <WatchlistPage />; }

/** /research/c/:symbol, ?tab=overview|forecasts|materials: one company.  An address whose code is not a ticker shows the page that says so (and the way back). */
export function CompanyRoute() {
  const symbol = useCompanyParam();
  const raw = useParams().symbol ?? "";
  if (!symbol) return <CompanyUnknown raw={raw} />;
  return <CompanyPage key={symbol} symbol={symbol} />;
}
