import { X } from "lucide-react";
import { Suspense, lazy } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import type { V2JobAlert } from "../../../api/forecast-v2";
import { jobFailurePhrase } from "../../../forecast-model.mjs";
import { translatePhrase, useLocale } from "../../../i18n";
import "../../../styles/forecast.css";
import { dismissFailure, useJobFailures, type JobFailure } from "./jobs";

// The bar is a chunk of its own, fetched when a task runs (the shell's dock does the same).
const TaskBar = lazy(() => import("@/components/state/TaskBar").then(m => ({ default: m.TaskBar })));

/** What the server says of a job this page did not start (the list's `job_alerts`): waiting, running, or the reason it ended without a version. */
function alertText(alert: V2JobAlert): string {
  if (alert.status === "queued") return translatePhrase("已排队，等待处理");
  if (alert.status === "running") return translatePhrase("正在处理");
  return translatePhrase(jobFailurePhrase(alert.error_type) ?? "任务没有返回可识别的失败原因。");
}

/**
 * The jobs of the forecast pages, in one place above the lists (design 4.0, 长任务, and 4.6): what is running (stage and elapsed time, from the task
 * register), what the server reports for jobs started elsewhere, and what ended without a version, with the reason and 重试.  The retry is the old
 * one: the same request again.  While this strip is on the page the shell's own dock stays away (styles/forecast.css), so no row shows twice.
 */
export function TaskStrip({ alerts = [], onRetry }: { alerts?: V2JobAlert[]; onRetry?: (symbol: string) => void }) {
  const { t } = useLocale();
  const failures = useJobFailures();
  const known = new Set(failures.map(item => item.id));
  const server = alerts.filter(alert => !known.has(alert.job_id));
  const row = (key: string, symbol: string, kind: "progress" | "failure", text: string, extra: JobFailure | null) => <li key={key} data-slot="job-alert" data-kind={kind} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-line bg-surface px-3 py-2 text-small">
    <StatusBadge kind={kind} className="h-5">{symbol}</StatusBadge>
    <span className="min-w-0 flex-1 text-ink-2 [overflow-wrap:anywhere]">{text}{extra?.code && <> <code className="font-mono text-caption text-muted-foreground">{extra.code}</code></>}</span>
    {kind === "failure" && onRetry && <button type="button" onClick={() => { onRetry(symbol); if (extra) dismissFailure(extra.id); }} className="inline-flex h-8 items-center rounded-sm border border-line-strong bg-background px-3 text-small font-medium text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">{t("重试")}</button>}
    {extra && <button type="button" aria-label={t("忽略")} onClick={() => dismissFailure(extra.id)} className="inline-flex size-8 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"><X aria-hidden="true" className="size-4" /></button>}
  </li>;
  return <div data-task-strip="" data-testid="forecast-jobs" className="flex flex-col gap-2 empty:hidden">
    <Suspense fallback={null}><TaskBar /></Suspense>
    {(failures.length > 0 || server.length > 0) && <ul aria-label={t("预测任务提示")} className="m-0 flex list-none flex-col gap-1 p-0">
      {failures.map(item => row(item.id, item.symbol, "failure", item.phrase, item))}
      {server.map(alert => row(alert.job_id, alert.symbol, alert.status === "queued" || alert.status === "running" ? "progress" : "failure", alertText(alert), null))}
    </ul>}
  </div>;
}
