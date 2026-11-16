import { JudgmentPage } from "../research/forecasts/JudgmentPage";
import { ToForecastHome, useRecordParam } from "./frames";

/** /research/judgments/:eventId */
export function JudgmentRoute() {
  const eventId = useRecordParam("eventId");
  if (!eventId) return <ToForecastHome />;
  return <JudgmentPage key={eventId} judgmentId={eventId} />;
}
