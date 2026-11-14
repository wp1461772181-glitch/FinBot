import { useSearchParams } from "react-router";
import { SectionTabs } from "../../Shell";
import { MaterialLibrary } from "../../MaterialLibrary";
import { scanOfficialFilings } from "../../api";
import { materialFocusFromParams, symbolFromParams } from "../../routes.mjs";
import { isSupportedSymbol } from "../../OverviewWorkspace";
import { useWorkspace } from "../workspace";

/** The material library on one company, opened on a row when the address carries one (focus, type, analysis). */
export function MaterialsPage({ symbol, focus }: { symbol: string; focus: ReturnType<typeof materialFocusFromParams> | null }) {
  const ws = useWorkspace();
  async function scan() {
    if (!isSupportedSymbol(symbol)) throw new Error("SEC 扫描需要有效的美股代码。");
    return scanOfficialFilings(symbol);
  }
  return <><SectionTabs section="materials" navigate={ws.go} />
    <MaterialLibrary key={`${symbol}:${focus?.source_type ?? ""}:${focus?.source_id ?? ""}:${focus?.analysis_id ?? ""}`} symbol={symbol} focus={focus} onScan={scan} /></>;
}

/** /research/materials, ?symbol=&focus=&type=[&analysis=] */
export function MaterialsRoute() {
  const ws = useWorkspace();
  const [params] = useSearchParams();
  const focus = materialFocusFromParams(params);
  return <MaterialsPage symbol={symbolFromParams(params) ?? ws.symbol} focus={focus} />;
}
