import { useNavigate, useSearchParams } from "react-router";
import { ForecastHome } from "../../ForecastHome";
import { paths, symbolFromParams } from "../../routes.mjs";
import { useWorkspace } from "../workspace";

/** The forecast home, optionally filtered to one company. */
export function ForecastsPage({ symbolFilter }: { symbolFilter?: string }) {
  const ws = useWorkspace();
  const navigate = useNavigate();
  return <main className="workspace"><ForecastHome queue={ws.symbols} personal={ws.personal} symbolFilter={symbolFilter} onClearSymbol={() => navigate(paths.forecasts())} />
  </main>;
}

/** /research/forecasts, ?symbol= */
export function ForecastsRoute() {
  const [params] = useSearchParams();
  return <ForecastsPage symbolFilter={symbolFromParams(params) ?? undefined} />;
}
