import { useNavigate } from "react-router";
import { ForecastHome } from "./forecasts/ForecastHome";
import { MaterialLibrary } from "./materials/MaterialLibrary";
import { scanOfficialFilings } from "../../api/market-data";
import { paths } from "../../routes.mjs";
import { useWorkspace } from "../workspace";
import { isSupportedSymbol } from "./support";

// The company page's 预测 tab is the forecast home filtered to the company (P6.2); its 材料 tab is the material library on the company (P6.3).

/** The forecast home, filtered to one company. */
export function ForecastsTab({ symbol }: { symbol: string }) {
  const ws = useWorkspace();
  const navigate = useNavigate();
  return <div data-testid="company-forecasts"><ForecastHome embedded queue={ws.symbols} personal={ws.personal} symbolFilter={symbol} onClearSymbol={() => navigate(paths.forecasts())} /></div>;
}

/** The material library, on one company. */
export function MaterialsTab({ symbol }: { symbol: string }) {
  async function scan() {
    if (!isSupportedSymbol(symbol)) throw new Error("SEC 扫描需要有效的美股代码。");
    return scanOfficialFilings(symbol);
  }
  return <div data-testid="company-materials"><MaterialLibrary key={symbol} embedded symbol={symbol} focus={null} onScan={scan} /></div>;
}
