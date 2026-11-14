import { useEffect, useState } from "react";
import { Tx, useLocale } from "./i18n";
import { ApiError, createV2ForecastJob, getEarningsJudgment, getV2Forecasts, getV2Job } from "./api";
import type { EarningsJudgment, V2ForecastListRow } from "./api";
import type { V2ForecastJob } from "./types";
import { NOT_RECORDED } from "./forecast-model.mjs";
import { judgmentRowModel, promotionRequest, promotionState } from "./forecast-home.mjs";
import { hashHref, paths } from "./routes.mjs";
import { Parts, formatTime } from "./ForecastShared";
import type { ResourceState } from "./ForecastShared";
import { JobStatus, errorMessage, isActiveJob, saveJob } from "./ForecastJob";

const PROMOTION_REASON: Record<string, string> = {
  first_session_open: "首个交易日收盘后可用",
  filing_not_in_library: "这份财报还没进资料库，先到材料库扫描",
};

/**
 * `#forecast/judgment/<id>`: one earnings judgment with its reasons and the quotes they rest on.  It is a
 * different kind of record from a formal forecast (design §2), so it shows no probabilities and no versions.
 */
export function EarningsJudgmentPage({ judgmentId, onHome }: { judgmentId: string; onHome: () => void }) {
  const { t } = useLocale();
  const [state, setState] = useState<ResourceState<EarningsJudgment>>({ kind: "loading" });
  const [status, setStatus] = useState<number | null>(null);
  const [forecasts, setForecasts] = useState<V2ForecastListRow[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [activeJob, setActiveJob] = useState<V2ForecastJob | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    setStatus(null);
    getEarningsJudgment(judgmentId, controller.signal)
      .then((judgment) => { if (!controller.signal.aborted) setState({ kind: "ready", data: judgment }); })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setStatus(error instanceof ApiError ? error.status ?? null : null);
        setState({ kind: "error", message: "" });
      });
    return () => controller.abort();
  }, [judgmentId]);

  const symbol = state.kind === "ready" ? state.data.symbol : null;
  useEffect(() => {
    if (!symbol) return;
    const controller = new AbortController();
    getV2Forecasts({ symbols: [symbol], state: "open", limit: 5 }, controller.signal)
      .then((next) => { if (!controller.signal.aborted) setForecasts(next.forecasts); })
      .catch(() => { if (!controller.signal.aborted) setForecasts([]); });
    return () => controller.abort();
  }, [symbol, reloadKey]);

  // A started forecast is polled like on the home page; when it ends the open-forecast read above runs again.
  useEffect(() => {
    if (activeJob === null || !isActiveJob(activeJob)) return;
    const jobId = activeJob.id;
    const timer = window.setInterval(() => {
      getV2Job(jobId)
        .then((next) => { setActiveJob(next); if (!isActiveJob(next)) setReloadKey((value) => value + 1); })
        .catch((error: unknown) => setActionError(errorMessage(error, "无法刷新预测任务状态。")));
    }, 3_000);
    return () => window.clearInterval(timer);
  }, [activeJob]);

  async function promote(judgment: EarningsJudgment) {
    const request = promotionRequest(judgment);
    if (!request) return;
    setActionError(null);
    try {
      const job = await createV2ForecastJob(request.symbol, request.source_refs);
      setActiveJob(job);
      saveJob(request.symbol, job);
    } catch (error) {
      setActionError(errorMessage(error, "无法创建预测任务。"));
    }
  }

  if (state.kind === "loading") return <section className="v2-desk"><p role="status">{t("正在读取…")}</p></section>;
  if (state.kind === "error") {
    const ownerOnly = status === 401 || status === 403;
    return <section className="v2-desk" aria-labelledby="judgment-title">
      <header className="v2-desk-heading"><div>
        <h2 id="judgment-title">{t(ownerOnly ? "登录个人账户后才能查看财报判断" : status === 404 ? "找不到这项财报判断" : "财报判断暂时无法读取。")}</h2>
      </div></header>
      <button className="secondary-action" type="button" onClick={onHome}>{t("回到预测首页")}</button>
    </section>;
  }
  const judgment = state.data;
  const model = judgmentRowModel(judgment);
  const openForecast = forecasts[0] ?? null;
  const promotion = promotionState(judgment, openForecast);
  return <section className="v2-desk judgment-page" aria-labelledby="judgment-title">
    <header className="v2-desk-heading">
      <div>
        <p className="eyebrow">{t(model.typeLabel)}</p>
        <h2 id="judgment-title">{judgment.symbol} · {t(model.direction)}{model.confidence ? ` · ${t(model.confidence)}` : ""}</h2>
        <p>{t(model.typeNote)}</p>
        <p className="v2-limit">{t("模型意见，未经盲测，仅供参考；买不买由你决定。")}</p>
      </div>
      <button className="secondary-action" type="button" onClick={onHome}>{t("回到预测首页")}</button>
    </header>

    {!judgment.delivered && <p className="v2-notice" role="status">{t("这条判断没有发送给你。")}</p>}

    <section className="v2-card">
      <p className="section-label">{t("理由（附原文）")}</p>
      {judgment.reasons.length === 0 ? <p>{t(NOT_RECORDED)}</p> : <ol className="judgment-reasons">
        {judgment.reasons.map((reason, index) => <li key={index}><p>{reason.text}</p><blockquote>“{reason.quote}”</blockquote></li>)}
      </ol>}
      {judgment.counter_argument && <><p className="section-label">{t("反方")}</p><p>{judgment.counter_argument}</p></>}
    </section>

    <section className="v2-card">
      <dl>
        <div><dt>{t("结果")}</dt><dd>{t(model.result)}</dd></div>
        {model.afterHours && <div><dt>{t("盘后走势")}</dt><dd><Parts parts={model.afterHours.parts} /></dd></div>}
        <div><dt>{t("决策模型")}</dt><dd>{model.model ?? t(NOT_RECORDED)}{model.modelFirstStage ? ` (${t("首条消息时的模型")})` : ""}</dd></div>
        <div><dt>{t("财报发布时间")}</dt><dd>{formatTime(judgment.accepted_at)}</dd></div>
        {judgment.source_url && <div><dt>{t("原文")}</dt><dd><a href={judgment.source_url} target="_blank" rel="noopener noreferrer">{<Tx text={"打开原始来源"} />}</a></dd></div>}
      </dl>
    </section>

    <section className="v2-card judgment-promotion" aria-label={t("基于这份财报")}>
      <p className="section-label">{t("基于这份财报")}</p>
      {promotion.state === "create" && <button className="primary-action" type="button" onClick={() => void promote(judgment)} disabled={isActiveJob(activeJob)}>
        {isActiveJob(activeJob) ? t("任务处理中…") : t("基于这份财报创建正式预测")}
      </button>}
      {promotion.state === "revise" && openForecast && judgment.filing_source_id && <a className="secondary-action" href={hashHref(paths.forecast(openForecast.id, { revise: judgment.filing_source_id }))}>{t("用这份财报修订")}</a>}
      {promotion.state === "unavailable" && promotion.reason && <p role="status">
        {t(PROMOTION_REASON[promotion.reason])}
        {promotion.reason === "filing_not_in_library" && <> · <a href={hashHref(paths.materials({ symbol: judgment.symbol }))}>{t("打开资料库")}</a></>}
      </p>}
      {promotion.state !== "unavailable" && <small className="v2-limit">{t("新预测只从这份财报的原文出发，不带这条判断的方向和理由。")}</small>}
      {activeJob && <JobStatus job={activeJob} />}
      {actionError && <p className="v2-notice error" role="alert">{actionError}</p>}
    </section>

    {openForecast && <p className="v2-limit">
      {t("两者问题不同：财报判断看首个交易日，正式预测看 20 个交易日。")} <a href={hashHref(paths.forecast(openForecast.id))}>{t("查看这家公司的正式预测")}</a>
    </p>}
  </section>;
}
