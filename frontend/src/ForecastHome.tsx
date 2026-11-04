import { useEffect, useMemo, useState } from "react";
import { Tx, translatePhrase, useLocale } from "./i18n";
import { createV2ForecastJob, getEarningsJudgments, getModelRoles, getPortfolio, getV2Forecasts, getV2Job, getV2MonitorStatus } from "./api";
import type { EarningsJudgment, V2ForecastList, V2JobAlert } from "./api";
import type { V2ForecastJob, V2MonitorStatus } from "./types";
import { jobFailurePhrase } from "./forecast-model.mjs";
import { filterRows, filterScopes, formalRowModel, judgmentLane, judgmentRowModel, sortForAttention, splitDelivered, symbolMark, symbolsWithBoth } from "./forecast-home.mjs";
import type { ForecastScope, JudgmentLane } from "./forecast-home.mjs";
import { FormalForecastRow } from "./FormalForecastRow";
import { JudgmentRow } from "./JudgmentRow";
import { JobStatus, errorMessage, isActiveJob, saveJob } from "./ForecastJob";
import type { ResourceState } from "./ForecastShared";

const SCOPE_LABEL: Record<ForecastScope, string> = { all: "全部", holdings: "持仓", queue: "研究队列" };
type Lane = JudgmentLane<EarningsJudgment>;

function alertText(alert: V2JobAlert): string {
  if (alert.status === "queued") return translatePhrase("已排队，等待处理");
  if (alert.status === "running") return translatePhrase("正在处理");
  return translatePhrase(jobFailurePhrase(alert.error_type) ?? "任务没有返回可识别的失败原因。");
}

function monitorProblem(monitor: V2MonitorStatus | null): string | null {
  if (!monitor || monitor.health === "healthy") return null;
  if (monitor.health === "delayed") return translatePhrase("运行延迟");
  if (monitor.health === "degraded") return translatePhrase("部分失败或降级");
  return translatePhrase("没有运行记录");
}

/**
 * `#forecast`: every company's forecasts in one place, in two lanes that never share a row component
 * (design §1.2 Level 1 and §2).  The page makes a fixed number of requests, however long the queue is.
 */
export function ForecastHome({ queue, personal, symbolFilter, onClearSymbol }: { queue: string[]; personal: boolean; symbolFilter?: string; onClearSymbol: () => void }) {
  const { t } = useLocale();
  const [list, setList] = useState<ResourceState<V2ForecastList>>({ kind: "loading" });
  const [lane, setLane] = useState<Lane | null>(null);
  const [holdings, setHoldings] = useState<string[] | null>(null);
  const [monitor, setMonitor] = useState<V2MonitorStatus | null>(null);
  const [forecastRole, setForecastRole] = useState<string | null | undefined>(undefined);
  const [scope, setScope] = useState<ForecastScope>("all");
  const [reloadKey, setReloadKey] = useState(0);
  const [createSymbol, setCreateSymbol] = useState("");
  const [activeJob, setActiveJob] = useState<V2ForecastJob | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    setList({ kind: "loading" });
    getV2Forecasts({ limit: 200 }, signal)
      .then((next) => { if (!signal.aborted) setList({ kind: "ready", data: next }); })
      .catch((error: unknown) => { if (!signal.aborted) setList({ kind: "error", message: errorMessage(error, "暂时无法读取预测日期列表。") }); });
    getV2MonitorStatus(signal).then((next) => { if (!signal.aborted) setMonitor(next); }).catch(() => { if (!signal.aborted) setMonitor(null); });
    if (personal) {
      Promise.allSettled([getEarningsJudgments({ limit: 100 }, signal)]).then(([result]) => { if (!signal.aborted) setLane(judgmentLane(result)); });
      getPortfolio(signal).then((next) => { if (!signal.aborted) setHoldings(next.positions.map((position) => position.symbol)); }).catch(() => { if (!signal.aborted) setHoldings(null); });
      getModelRoles(signal).then((next) => { if (!signal.aborted) setForecastRole(next.roles.forecast ?? null); }).catch(() => { if (!signal.aborted) setForecastRole(undefined); });
    } else {
      setLane({ lane: "hidden" });
      setHoldings(null);
    }
    return () => controller.abort();
  }, [personal, reloadKey]);

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

  const scopes = filterScopes(holdings !== null);
  const activeScope = scopes.includes(scope) ? scope : "all";
  const heldSymbols = holdings ?? [];
  const rows = useMemo(() => {
    if (list.kind !== "ready") return [];
    const bySymbol = symbolFilter ? list.data.forecasts.filter((row) => row.symbol === symbolFilter) : list.data.forecasts;
    return filterRows(bySymbol, activeScope, heldSymbols, queue);
  }, [list, symbolFilter, activeScope, heldSymbols, queue]);
  const sorted = useMemo(() => sortForAttention(rows, list.kind === "ready" ? list.data.job_alerts : [], new Date()), [rows, list]);
  const judgments = useMemo(() => {
    if (lane?.lane !== "ready") return [];
    const bySymbol = symbolFilter ? lane.judgments.filter((item) => item.symbol === symbolFilter) : lane.judgments;
    return filterRows(bySymbol, activeScope, heldSymbols, queue);
  }, [lane, symbolFilter, activeScope, heldSymbols, queue]);
  const { delivered, skipped } = splitDelivered(judgments);
  const both = symbolsWithBoth(rows, judgments);
  const choices = useMemo(() => [...new Set([...queue, ...heldSymbols])].sort(), [queue, heldSymbols]);
  const problem = monitorProblem(monitor);
  const alerts = list.kind === "ready" ? list.data.job_alerts : [];

  async function createForecast() {
    const symbol = createSymbol || choices[0];
    if (!symbol) return;
    setActionError(null);
    try {
      const job = await createV2ForecastJob(symbol);
      setActiveJob(job);
      saveJob(symbol, job);
    } catch (error) {
      setActionError(errorMessage(error, "无法创建预测任务。"));
    }
  }

  return <section className="v2-desk forecast-home" aria-labelledby="forecast-home-title">
    <header className="v2-desk-heading">
      <div>
        <p className="eyebrow">{t("所有公司")}</p>
        <h2 id="forecast-home-title">{t("预测")}</h2>
        <p>{t("概率未经校准，属实验性信息。仅供参考，买不买由你决定。")}</p>
      </div>
      {personal && choices.length > 0 && <div className="forecast-create">
        <label className="visually-hidden" htmlFor="forecast-create-symbol">{t("选择股票")}</label>
        <select id="forecast-create-symbol" value={createSymbol || choices[0]} onChange={(event) => setCreateSymbol(event.target.value)}>
          {choices.map((symbol) => <option key={symbol} value={symbol}>{symbol}</option>)}
        </select>
        <button className="primary-action" type="button" onClick={createForecast} disabled={isActiveJob(activeJob)}>{isActiveJob(activeJob) ? t("任务处理中…") : t("创建预测")}</button>
        {forecastRole !== undefined && <small>{forecastRole ? <>{t("下一次预测使用：")}{forecastRole}</> : t("下一次预测使用：服务器默认模型（设置中未绑定预测模型）")}</small>}
      </div>}
    </header>

    {problem && <p className="v2-notice" role="status">{t("监控状态：")}{problem} · <a href="#forecast/monitor">{t("查看监控状态")}</a></p>}
    {activeJob && <JobStatus job={activeJob} />}
    {actionError && <p className="v2-notice error" role="alert">{actionError}</p>}
    {alerts.length > 0 && <ul className="forecast-alerts" aria-label={t("预测任务提示")}>
      {alerts.map((alert) => <li key={alert.job_id}><strong>{alert.symbol}</strong> {alertText(alert)}</li>)}
    </ul>}

    <div className="forecast-filters" role="group" aria-label={t("筛选")}>
      {scopes.map((item) => <button key={item} type="button" className={item === activeScope ? "is-active" : ""} aria-pressed={item === activeScope} onClick={() => setScope(item)}>{t(SCOPE_LABEL[item])}</button>)}
      {symbolFilter && <button type="button" className="tag" onClick={onClearSymbol}>{symbolFilter} ×</button>}
    </div>

    <section className="forecast-lane" aria-labelledby="lane-formal-title">
      <h3 id="lane-formal-title">{t("正式预测")}</h3>
      {list.kind === "loading" && <p role="status">{t("正在读取…")}</p>}
      {list.kind === "error" && <p className="v2-notice error" role="alert">{list.message}</p>}
      {list.kind === "ready" && sorted.length === 0 && <p>{t(symbolFilter || activeScope !== "all" ? "没有符合筛选条件的预测。" : "还没有预测。创建第一项预测后会出现在这里。")}</p>}
      {sorted.length > 0 && <ul className="forecast-rows">
        {sorted.map(({ row, tier }) => <FormalForecastRow key={row.id} model={formalRowModel(row, { holdings: heldSymbols, queue })} tier={tier} withJudgmentNote={both.has(row.symbol)} />)}
      </ul>}
    </section>

    {lane && lane.lane !== "hidden" && <section className="forecast-lane" aria-labelledby="lane-judgment-title">
      <h3 id="lane-judgment-title">{t("财报判断")}</h3>
      <p className="v2-limit">{t("模型意见，未经盲测，仅供参考；买不买由你决定。")}</p>
      {lane.lane === "error" && <p className="v2-notice error" role="alert">{t("财报判断暂时无法读取。")}</p>}
      {lane.lane === "ready" && delivered.length === 0 && skipped.length === 0 && <p>{t("还没有财报判断。")}</p>}
      {delivered.length > 0 && <ul className="forecast-rows">
        {delivered.map((item) => <JudgmentRow key={item.id} model={judgmentRowModel(item)} mark={symbolMark(item.symbol, heldSymbols, queue)} withForecastNote={both.has(item.symbol)} />)}
      </ul>}
      {skipped.length > 0 && <details className="forecast-skipped">
        <summary>{t("未发送")} {skipped.length} {t("条")}</summary>
        <ul className="forecast-rows">
          {skipped.map((item) => <JudgmentRow key={item.id} model={judgmentRowModel(item)} mark={symbolMark(item.symbol, heldSymbols, queue)} withForecastNote={both.has(item.symbol)} />)}
        </ul>
      </details>}
    </section>}

    <footer className="forecast-home-links">
      <a href="#evaluation">{<Tx text={"模型成绩"} />}</a> · <a href="#replay">{<Tx text={"历史回放"} />}</a> · <a href="#forecast/monitor">{<Tx text={"监控状态"} />}</a>
    </footer>
  </section>;
}
