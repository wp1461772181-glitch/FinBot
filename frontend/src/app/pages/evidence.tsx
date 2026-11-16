import { useParams, useSearchParams } from "react-router";
import { EvidencePage } from "../research/evidence/EvidencePage";
import { sourceTypeParam, symbolFromParams } from "../../routes.mjs";
import { useWorkspace } from "../workspace";

/** /research/evidence (a version picker's index form), /research/evidence/:versionId, /research/evidence/:versionId/:sourceType/:sourceId; ?symbol= names the company of the index form, ?upload=1 opens the upload dialog. */
export function EvidenceRoute() {
  const ws = useWorkspace();
  const { versionId, sourceType, sourceId } = useParams();
  const [params] = useSearchParams();
  const symbol = symbolFromParams(params) ?? ws.symbol;
  const type = sourceTypeParam(sourceType);
  const address = { versionId: versionId ?? null, sourceType: versionId && type && sourceId ? type : null, sourceId: versionId && type && sourceId ? sourceId : null };
  return <EvidencePage key={versionId ? "version" : symbol} symbol={symbol} companies={ws.symbols} address={address} uploadOpen={params.get("upload") === "1"} />;
}
