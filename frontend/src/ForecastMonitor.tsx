import { Tx, translatePhrase, useLocale } from "./i18n";
import type { V2MonitorStatus } from "./types";
import { formatTime } from "./ForecastShared";
import type { ResourceState } from "./ForecastShared";

export function MonitorCard({ monitor }: { monitor: ResourceState<V2MonitorStatus> }) {
  const { t } = useLocale();
  if (monitor.kind === "loading") return <article><span>{<Tx text={"自动监控"} />}</span><strong>{<Tx text={"正在读取记录"} />}</strong><small>{<Tx text={"尚未根据定时器配置判断健康。"} />}</small></article>;
  if (monitor.kind === "error") return <article><span>{<Tx text={"自动监控"} />}</span><strong>{<Tx text={"状态不可读取"} />}</strong><small>{<Tx text={"无法确认监控是否正常运行。"} />}</small></article>;
  const { health, last_run: lastRun } = monitor.data;
  return <article className={`v2-monitor-card is-${health}`}><span>{<Tx text={"自动监控"} />}</span><strong>{monitorHealthText(health)}</strong><small>{lastRun ? `${t("最近扫描")} ${formatTime(lastRun.completed_at ?? lastRun.started_at)}` : t("还没有持久化运行记录")}</small></article>;
}

export function MonitorDetail({ monitor }: { monitor: ResourceState<V2MonitorStatus> }) {
  const { locale, t } = useLocale();
  if (monitor.kind === "loading") return null;
  if (monitor.kind === "error") return <p className="v2-notice error" role="alert">{monitor.message}</p>;
  const { health, last_run: lastRun, last_success: lastSuccess, stale_after_seconds: staleAfter } = monitor.data;
  if (!lastRun) return <section className="v2-monitor-detail"><p className="section-label">{<Tx text={"自动监控记录"} />}</p><h3>{<Tx text={"没有运行记录"} />}</h3><p>{<Tx text={"没有实际扫描或成功记录时，页面不会把每小时计划显示为健康。"} />}</p></section>;
  const symbols = Object.entries(lastRun.per_symbol_results);
  return <section className={`v2-monitor-detail is-${health}`} aria-label={t("自动监控状态")}>
    <div><p className="section-label">{<Tx text={"自动监控记录"} />}</p><h3>{monitorHealthText(health)} · {t("最近运行")} {monitorRunStatusText(lastRun.status)}</h3><p>{locale === "en-US" ? `${t("检查开始")} ${formatTime(lastRun.started_at)}; ${t("完成")} ${formatTime(lastRun.completed_at)}; ${t("下一次预期")} ${formatTime(lastRun.next_due_at)}.` : `${t("检查开始")} ${formatTime(lastRun.started_at)}；${t("完成")} ${formatTime(lastRun.completed_at)}；${t("下一次预期")} ${formatTime(lastRun.next_due_at)}。`}</p><small>{locale === "en-US" ? `${t("延迟阈值为")} ${Math.round(staleAfter / 3600)} ${t("小时")}. ${t("最近扫描成功只代表一条持久化记录；定时健康需观察两个实际周期。")}` : `${t("延迟阈值为")} ${Math.round(staleAfter / 3600)} ${t("小时")}。${t("最近扫描成功只代表一条持久化记录；定时健康需观察两个实际周期。")}`}</small></div>
    <div className="v2-monitor-summary"><span>{<Tx text={"最近全成功"} />}</span><strong>{lastSuccess ? formatTime(lastSuccess.completed_at) : t("从未记录")}</strong>{lastRun.retry_reason && <small>{lastRun.retry_reason}</small>}</div>
    <div className="v2-monitor-symbols">{symbols.length ? symbols.map(([ticker, result]) => <article key={ticker} className={`is-${result.status}`}><strong>{ticker}</strong><span>{monitorSymbolStatusText(result.status)}</span><small>{result.error ?? `${t("发现")} ${result.discovered_count ?? 0} · ${t("新增")} ${result.created_count ?? 0} · ${t("入队")} ${result.queued_count ?? 0}`}</small></article>) : <p>{<Tx text={"本次运行没有返回逐股结果。"} />}</p>}</div>
  </section>;
}

function monitorHealthText(health: V2MonitorStatus["health"]) {
  switch (health) {
    case "healthy": return translatePhrase("最近扫描成功");
    case "delayed": return translatePhrase("运行延迟");
    case "degraded": return translatePhrase("部分失败或降级");
    default: return translatePhrase("没有运行记录");
  }
}

function monitorRunStatusText(status: "running" | "succeeded" | "partial" | "failed") {
  if (status === "succeeded") return translatePhrase("成功");
  if (status === "partial") return translatePhrase("部分失败");
  if (status === "failed") return translatePhrase("失败");
  return translatePhrase("进行中");
}

function monitorSymbolStatusText(status: "succeeded" | "incomplete" | "failed") {
  if (status === "succeeded") return translatePhrase("成功");
  if (status === "incomplete") return translatePhrase("未完整扫描");
  return translatePhrase("失败");
}
