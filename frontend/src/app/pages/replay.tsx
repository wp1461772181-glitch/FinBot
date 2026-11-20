import { ReplayPage } from "../research/replay/ReplayPage";
import { useWorkspace } from "../workspace";
import { EmptyWatchlist } from "./frames";

/** /research/replay (with an empty watchlist the page is the notice: add a company, or restore the defaults) */
export function ReplayRoute() {
  const ws = useWorkspace();
  if (!ws.symbols.length) return <EmptyWatchlist />;
  return <ReplayPage key={ws.symbol} initialSymbol={ws.symbol} symbols={ws.symbols} />;
}
