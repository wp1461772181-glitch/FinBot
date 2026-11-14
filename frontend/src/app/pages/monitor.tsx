import { useNavigate } from "react-router";
import { ForecastMonitorPage } from "../../ForecastMonitorPage";
import { paths } from "../../routes.mjs";

/** /research/monitor */
export function MonitorRoute() {
  const navigate = useNavigate();
  return <main className="workspace"><ForecastMonitorPage onHome={() => navigate(paths.forecasts())} /></main>;
}
