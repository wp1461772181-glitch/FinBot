import { Link } from "react-router";
import { OpinionCard } from "@/components/OpinionCard";
import { Skeleton, useDelayedFlag } from "@/components/state/Skeleton";
import { useLocale } from "../../i18n";
import { NOT_RECORDED } from "../../forecast-model.mjs";
import { researchRecord } from "../../portfolio-items.mjs";
import { paths } from "../../routes.mjs";
import { Parts } from "../../ForecastShared";
import type { ResearchLists } from "./use-portfolio";

/**
 * 研究记录: what the research side holds on this symbol, one line each for the latest open forecast and the latest earnings judgment (portfolio-items.mjs's
 * researchRecord, the page's one list read for every position).  It is the model's opinion quoted, so it is the opinion material, labelled 模型意见, with a link to
 * the page of each; the disclaimer is its footnote, and it is there only when a probability is (a judgment keeps its own words); the page opens one position at a time, so the sentence is on screen once.  The figures are plain text,
 * no up / down colour: an uncalibrated number must not read as a signal beside the reader's own plan.  No record says so.
 */
export function ResearchRecord({ symbol, lists }: { symbol: string; lists: ResearchLists }) {
  const { t } = useLocale();
  const pending = useDelayedFlag(lists.state === "loading");
  const { forecast, judgment } = researchRecord(symbol, lists.forecasts, lists.judgments);
  const missing = lists.state === "partial" || lists.state === "failed";
  let body;
  if (!forecast && !judgment) {
    body = lists.state === "loading"
      ? <span role="status" aria-busy="true" className="block">{pending && <Skeleton className="h-4 w-2/3" />}</span>
      : <p className="text-small text-muted-foreground">{missing ? t("研究记录暂时读不到。") : t("暂无研究记录")}</p>;
    return <section data-testid="pf-research" aria-label={t("研究记录")} className="flex min-w-0 flex-col gap-1.5">
      <h4 className="text-small font-medium text-ink">{t("研究记录")}</h4>{body}
    </section>;
  }
  return <section data-testid="pf-research" aria-label={t("研究记录")} className="flex min-w-0 flex-col gap-1.5">
    <h4 className="text-small font-medium text-ink">{t("研究记录")}</h4>
    <OpinionCard data-testid="pf-research-opinion" className="gap-2 p-3" disclaimer={Boolean(forecast?.percent)}>
      {forecast && <p data-testid="pf-research-forecast" className="text-small text-ink [overflow-wrap:anywhere]">
        <Link to={paths.forecast(forecast.id)} className="rounded-sm text-brand underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"><Parts parts={forecast.titleParts} /></Link>
        {forecast.percent ? ` · ${t("下跌")} ${forecast.percent.bearish}% · ${t("持平")} ${forecast.percent.neutral}% · ${t("上涨")} ${forecast.percent.bullish}%` : ""}
        {` · ${t("目标日")} ${forecast.targetDate ?? t(NOT_RECORDED)} · ${t("决策模型")} ${forecast.model ?? t(NOT_RECORDED)}`}
      </p>}
      {judgment && <p data-testid="pf-research-judgment" className="text-small text-ink [overflow-wrap:anywhere]">
        <Link to={paths.judgment(judgment.id)} className="rounded-sm text-brand underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{t(judgment.typeLabel)}</Link>
        {` · ${t(judgment.direction)}${judgment.confidence ? ` · ${t(judgment.confidence)}` : ""} · ${t(judgment.result)}`}
        {judgment.afterHours && <> · <Parts parts={judgment.afterHours.parts} /></>}
        {!judgment.delivered && ` · ${t("未发送")}`}
      </p>}
    </OpinionCard>
    {missing && <p className="text-caption text-muted-foreground">{t("研究记录暂时读不到。")}</p>}
  </section>;
}
