import { useNavigate } from "react-router";
import { EarningsJudgmentPage } from "../../EarningsJudgmentPage";
import { paths } from "../../routes.mjs";
import { ToForecastHome, useRecordParam } from "./frames";

/** /research/judgments/:eventId */
export function JudgmentRoute() {
  const navigate = useNavigate();
  const eventId = useRecordParam("eventId");
  if (!eventId) return <ToForecastHome />;
  return <main className="workspace"><EarningsJudgmentPage key={eventId} judgmentId={eventId} onHome={() => navigate(paths.forecasts())} /></main>;
}
