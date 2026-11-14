import { useNavigate } from "react-router";
import { SectionTabs } from "../../Shell";
import { EarningsJudgmentPage } from "../../EarningsJudgmentPage";
import { paths } from "../../routes.mjs";
import { ToForecastHome, useRecordParam } from "./frames";
import { useWorkspace } from "../workspace";

/** /research/judgments/:eventId */
export function JudgmentRoute() {
  const ws = useWorkspace();
  const navigate = useNavigate();
  const eventId = useRecordParam("eventId");
  if (!eventId) return <ToForecastHome />;
  return <main className="workspace"><SectionTabs section="forecast" navigate={ws.go} />
    <EarningsJudgmentPage key={eventId} judgmentId={eventId} onHome={() => navigate(paths.forecasts())} />
  </main>;
}
