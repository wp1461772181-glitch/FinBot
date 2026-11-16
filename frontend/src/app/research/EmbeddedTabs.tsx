import { useNavigate } from "react-router";
import { ForecastHome } from "../../ForecastHome";
import { LegacyFrame } from "../../LegacyFrame";
import { MaterialLibrary } from "../../MaterialLibrary";
import { scanOfficialFilings } from "../../api/market-data";
import { paths } from "../../routes.mjs";
import { useWorkspace } from "../workspace";
import { isSupportedSymbol } from "./support";

// The company page's 预测 and 材料 tabs show the old pages, scoped to the company, until they are redone (P6.2 the forecasts, P6.3 the materials).  Each sits in
// the old-UI frame (its own styles); the wrapper takes away the page padding the old pages brought, because the company page already has its own.

/** The old forecast home, filtered to one company. */
export function ForecastsTab({ symbol }: { symbol: string }) {
  const ws = useWorkspace();
  const navigate = useNavigate();
  return <LegacyFrame><div className="workspace p-0" data-testid="company-forecasts"><ForecastHome queue={ws.symbols} personal={ws.personal} symbolFilter={symbol} onClearSymbol={() => navigate(paths.forecasts())} /></div></LegacyFrame>;
}

/** The old material library, on one company. */
export function MaterialsTab({ symbol }: { symbol: string }) {
  async function scan() {
    if (!isSupportedSymbol(symbol)) throw new Error("SEC 扫描需要有效的美股代码。");
    return scanOfficialFilings(symbol);
  }
  return <LegacyFrame><div className="workspace p-0" data-testid="company-materials"><MaterialLibrary key={symbol} symbol={symbol} focus={null} onScan={scan} /></div></LegacyFrame>;
}
