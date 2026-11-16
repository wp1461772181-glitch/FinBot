import { useSearchParams } from "react-router";
import { ForecastDetail } from "../research/forecasts/ForecastDetail";
import { isRecordId } from "../../routes.mjs";
import { ToForecastHome, useRecordParam } from "./frames";

/** /research/forecasts/:rootId, ?version= ?revise= ?section= (versions | evaluation | audit; the old #revisions address resolves to ?section=versions). */
export function ForecastRoute() {
  const rootId = useRecordParam("rootId");
  const [params] = useSearchParams();
  const version = params.get("version");
  // An unreadable ?version= is a malformed address: the home, never a guess at another record.
  if (!rootId || (version !== null && !isRecordId(version))) return <ToForecastHome />;
  const versionId = version ? version.toLowerCase() : undefined;
  const revise = params.get("revise");
  const reviseSourceId = revise && isRecordId(revise) ? revise.toLowerCase() : undefined;
  const section = params.get("section");
  return <ForecastDetail key={`${rootId}:${versionId ?? ""}:${reviseSourceId ?? ""}:${section ?? ""}`} rootId={rootId} versionId={versionId} reviseSourceId={reviseSourceId} section={section} />;
}
