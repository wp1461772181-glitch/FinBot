import { useNavigate, useSearchParams } from "react-router";
import { ForecastHome } from "../research/forecasts/ForecastHome";
import { paths, symbolFromParams } from "../../routes.mjs";
import { useWorkspace } from "../workspace";

/** The forecast home, optionally filtered to one company. */
export function ForecastsPage({ symbolFilter }: { symbolFilter?: string }) {
  const ws = useWorkspace();
  const navigate = useNavigate();
  return <ForecastHome queue={ws.symbols} personal={ws.personal} symbolFilter={symbolFilter} onClearSymbol={() => navigate(paths.forecasts())} />;
}

/** /research/forecasts, ?symbol= */
export function ForecastsRoute() {
  const [params] = useSearchParams();
  return <ForecastsPage symbolFilter={symbolFromParams(params) ?? undefined} />;
}
