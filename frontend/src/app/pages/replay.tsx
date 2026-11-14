import { HistoricalReplayWorkspace } from "../../HistoricalReplayWorkspace";
import { ResearchFrame } from "./frames";
import { useWorkspace } from "../workspace";

/** /research/replay */
export function ReplayRoute() {
  const ws = useWorkspace();
  return <ResearchFrame section="replay"><HistoricalReplayWorkspace key={ws.symbol} initialSymbol={ws.symbol} symbols={ws.symbols} /></ResearchFrame>;
}
