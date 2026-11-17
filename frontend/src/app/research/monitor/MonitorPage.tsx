import { Link } from "react-router";
import { DelayedSkeleton, SkeletonCard, SkeletonRows } from "@/components/state/Skeleton";
import { ErrorBar } from "@/components/state/ErrorBar";
import { actionMessage } from "../support";
import { useRead } from "../use-read";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { HealthCard } from "./HealthCard";
import { RunTimeline } from "./RunTimeline";
import { SymbolResults } from "./SymbolResults";
import { readMonitorStatus } from "./read-monitor";

/**
 * 监控 (#/research/monitor, design 4.8): the health card, then the last runs as a timeline and the company-by-company results.  The data is the one status read (GET
 * /v2/monitor/status), the same one the chips and the navigation's dot take their state from.  A page that cannot read it says so in its own place and offers 重试.
 */
export function MonitorPage() {
  const { t } = useLocale();
  const [monitor, retry] = useRead("monitor-page", signal => readMonitorStatus(signal));
  const status = monitor.kind === "ready" ? monitor.value : null;
  return <main data-testid="monitor-page" aria-labelledby="monitor-title" className="mx-auto flex w-full min-w-0 max-w-[1280px] flex-1 flex-col gap-4 p-4 lg:p-6">
    <header className="flex flex-wrap items-end gap-x-4 gap-y-2">
      <div className="min-w-0"><p className="text-caption text-muted-foreground">{t("预测")}</p><h1 id="monitor-title" className="text-title-m text-ink">{t("监控状态")}</h1></div>
      <Link to={paths.forecasts()} className="ml-auto inline-flex h-9 items-center rounded-sm border border-line-strong bg-background px-3 text-small font-medium text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11">{t("回到预测首页")}</Link>
    </header>
    {monitor.kind === "loading" && <DelayedSkeleton><div className="flex flex-col gap-4"><SkeletonCard /><div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]"><SkeletonRows rows={3} /><SkeletonRows rows={5} /></div></div></DelayedSkeleton>}
    {monitor.kind === "error" && <ErrorBar message={actionMessage(monitor.error, "暂时无法读取自动监控记录。")} onRetry={retry} />}
    {status && <>
      <HealthCard status={status} />
      {status.last_run && <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <RunTimeline status={status} />
        <SymbolResults run={status.last_run} />
      </div>}
    </>}
  </main>;
}
