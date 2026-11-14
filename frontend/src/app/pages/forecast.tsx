import { useNavigate, useSearchParams } from "react-router";
import { ForecastPage } from "../../ForecastPage";
import { isRecordId, paths } from "../../routes.mjs";
import { ToForecastHome, useRecordParam } from "./frames";

/** /research/forecasts/:rootId, ?version= ?revise= (and ?section=versions, which the old #revisions address resolves to). */
export function ForecastRoute() {
  const navigate = useNavigate();
  const rootId = useRecordParam("rootId");
  const [params] = useSearchParams();
  const version = params.get("version");
  // An unreadable ?version= is a malformed address: the home, never a guess at another record.
  if (!rootId || (version !== null && !isRecordId(version))) return <ToForecastHome />;
  const versionId = version ? version.toLowerCase() : undefined;
  const revise = params.get("revise");
  const reviseSourceId = revise && isRecordId(revise) ? revise.toLowerCase() : undefined;
  const focusVersions = params.get("section") === "versions";
  const goHome = () => navigate(paths.forecasts());
  return <main className="workspace"><ForecastPage key={`${rootId}:${versionId ?? ""}:${reviseSourceId ?? ""}:${focusVersions}`} rootId={rootId} versionId={versionId} reviseSourceId={reviseSourceId} focusVersions={focusVersions} onHome={goHome} /></main>;
}

