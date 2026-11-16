import { useNavigate } from "react-router";
import { ForecastHome } from "./forecasts/ForecastHome";
import { LegacyFrame } from "../../LegacyFrame";
import { MaterialLibrary } from "../../MaterialLibrary";
import { scanOfficialFilings } from "../../api/market-data";
import { paths } from "../../routes.mjs";
import { useWorkspace } from "../workspace";
import { isSupportedSymbol } from "./support";

// The company page's 预测 tab is the forecast home filtered to the company (P6.2); the 材料 tab still shows the old material library, scoped to the company, until it
// is redone (P6.3).  The old page sits in the old-UI frame (its own styles); the wrapper takes away the page padding it brought, because the company page already has its own.

/** The forecast home, filtered to one company. */
export function ForecastsTab({ symbol }: { symbol: string }) {
  const ws = useWorkspace();
  const navigate = useNavigate();
  return <div data-testid="company-forecasts"><ForecastHome embedded queue={ws.symbols} personal={ws.personal} symbolFilter={symbol} onClearSymbol={() => navigate(paths.forecasts())} /></div>;
}

/** The old material library, on one company. */
export function MaterialsTab({ symbol }: { symbol: string }) {
  async function scan() {
    if (!isSupportedSymbol(symbol)) throw new Error("SEC 扫描需要有效的美股代码。");
    return scanOfficialFilings(symbol);
  }
  return <LegacyFrame><div className="workspace p-0" data-testid="company-materials"><MaterialLibrary key={symbol} symbol={symbol} focus={null} onScan={scan} /></div></LegacyFrame>;
}
