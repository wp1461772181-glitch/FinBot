import { Tx, translatePhrase, useLocale } from "./i18n";
import { ApiError } from "./api";
import type { V2ForecastJob } from "./types";
import { jobFailurePhrase } from "./forecast-model.mjs";
import { formatTime } from "./ForecastShared";

export function errorMessage(error: unknown, fallback: string) {
  return translatePhrase(error instanceof ApiError ? error.message : fallback);
}

export function isActiveJob(job: V2ForecastJob | null) {
  return job?.status === "queued" || job?.status === "running";
}

function savedJobKey(symbol: string) {
  return `market-evidence-agent:v2-job:${symbol}`;
}

export function saveJob(symbol: string, job: V2ForecastJob) {
  try { window.localStorage.setItem(savedJobKey(symbol), job.id); } catch { /* Storage is optional; the job itself remains durable. */ }
}

export function savedJob(symbol: string) {
  try { return window.localStorage.getItem(savedJobKey(symbol)); } catch { return null; }
}

export function clearSavedJob(symbol: string) {
  try { window.localStorage.removeItem(savedJobKey(symbol)); } catch { /* No storage access does not affect server state. */ }
}

function jobStatusText(job: V2ForecastJob) {
  if (job.status === "queued") return translatePhrase("已排队，等待处理");
  if (job.status === "running") return translatePhrase("正在处理");
  if (job.status === "succeeded") return translatePhrase("已生成预测版本");
  if (job.status === "succeeded_no_change") return translatePhrase("已完成，但输入没有产生新版本");
  if (job.status === "blocked_data") return `${translatePhrase("未生成预测：")}${jobFailureText(job.error?.type)}`;
  return `${translatePhrase("处理未完成：")}${jobFailureText(job.error?.type)}`;
}

function jobFailureText(code?: string | null) {
  const phrase = jobFailurePhrase(code);
  if (phrase) return translatePhrase(phrase);
  return `${translatePhrase("任务未完成（")}${code}${translatePhrase("），没有发布预测版本。")}`;
}

export function JobStatus({ job }: { job: V2ForecastJob }) {
  const { t } = useLocale();
  const error = job.error?.type;
  return <section className={`v2-job-status is-${job.status}`} aria-live="polite">
    <div><span className="section-label">{t("当前任务")} · {t(job.kind === "manual_revision" ? "人工修订" : "新预测")}</span><strong>{jobStatusText(job)}</strong><small>{t("阶段")}：{translatePhrase(job.current_stage)} · {t("创建于")} {formatTime(job.created_at)}</small></div>
    <div className="v2-job-result">{job.result_version_id ? <>{<Tx text={"结果版本"} />}<br /><code>{job.result_version_id.slice(0, 8)}</code></> : error ? <>{<Tx text={"安全错误码"} />}<br /><code>{error}</code></> : <>{<Tx text={"任务编号"} />}<br /><code>{job.id.slice(0, 8)}</code></>}</div>
  </section>;
}
