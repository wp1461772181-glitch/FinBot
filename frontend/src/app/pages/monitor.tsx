import { useNavigate } from "react-router";
import { SectionTabs } from "../../Shell";
import { ForecastMonitorPage } from "../../ForecastMonitorPage";
import { paths } from "../../routes.mjs";
import { useWorkspace } from "../workspace";

/** /research/monitor */
export function MonitorRoute() {
  const ws = useWorkspace();
  const navigate = useNavigate();
  return <main className="workspace"><SectionTabs section="forecast" navigate={ws.go} />
    <ForecastMonitorPage onHome={() => navigate(paths.forecasts())} />
  </main>;
}
