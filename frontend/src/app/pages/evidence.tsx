import { useParams, useSearchParams } from "react-router";
import { EvidenceCenter, type EvidenceRoute } from "../../EvidenceCenter";
import { isSupportedSymbol } from "../../OverviewWorkspace";
import { sourceTypeParam, symbolFromParams } from "../../routes.mjs";
import { ResearchFrame } from "./frames";
import { useWorkspace } from "../workspace";

/** /research/evidence (the version picker), /research/evidence/:versionId, /research/evidence/:versionId/:sourceType/:sourceId. */
export function EvidenceRoute() {
  const ws = useWorkspace();
  const { versionId, sourceType, sourceId } = useParams();
  const [params] = useSearchParams();
  const symbol = symbolFromParams(params) ?? ws.symbol;
  const type = sourceTypeParam(sourceType);
  const route: EvidenceRoute | null = versionId && type && sourceId ? { versionId, sourceType: type, sourceId } : null;
  return <ResearchFrame section="evidence">
    <EvidenceCenter key={symbol} symbol={symbol} supported={isSupportedSymbol(symbol)} route={route} uploadOpen={params.get("upload") === "1"}
      onOpenForecast={() => ws.go("forecast")} />
  </ResearchFrame>;
}
