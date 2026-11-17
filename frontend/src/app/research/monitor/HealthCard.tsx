import { cn } from "@/lib/utils";
import type { V2MonitorStatus } from "../../../types";
import { formatDateTime, getLocalePreference, useLocale } from "../../../i18n";
import { MonitorBadge } from "./MonitorBadge";
import { monitorState, staleHours } from "./monitor-model.mjs";

// The edge colour of each state: success, the action colour (amber), failure, neutral.  A colour is never the only sign: the badge carries the icon and the words.
const EDGE: Record<string, string> = { success: "border-l-success", action: "border-l-action", failure: "border-l-danger", neutral: "border-l-line-strong" };

const when = (value: string | null | undefined, locale: "zh-CN" | "en-US") => (value ? formatDateTime(value, locale, "UTC") : null);

/**
 * The health of the automatic monitor (design 4.8): the state in words with its fixed icon and colour, when it last succeeded and when it is next due.  The state is
 * the server's `health`; with no run on record the card says so and does not show the hourly schedule as health.
 */
export function HealthCard({ status }: { status: V2MonitorStatus }) {
  const { t, locale } = useLocale();
  const state = monitorState(status.health);
  const run = status.last_run;
  const never = t("从未记录");
  const field = (label: string, value: string | null, testid: string) => <div key={testid} className="flex min-w-0 flex-col gap-0.5"><dt className="text-caption text-muted-foreground">{label}</dt><dd data-testid={testid} className="m-0 font-mono text-small tabular-nums text-ink [overflow-wrap:anywhere]">{value ?? "—"}</dd></div>;
  const errors = Object.entries(run?.error_summary ?? {});
  return <section data-testid="monitor-health" data-state={state.id} aria-label={t("自动监控状态")} className={cn("flex min-w-0 flex-col gap-3 rounded-md border border-l-4 border-line bg-surface p-4", EDGE[state.kind])}>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <MonitorBadge health={status.health} />
      <h2 data-testid="monitor-headline" className="text-title-s text-ink">{t(state.headline)}</h2>
    </div>
    {run
      ? <>
        <dl className="m-0 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-3">
          {field(t("最近扫描"), when(run.completed_at ?? run.started_at, locale), "monitor-last-scan")}
          {field(t("最近全成功"), status.last_success ? when(status.last_success.completed_at, locale) : never, "monitor-last-success")}
          {field(t("下一次预期"), when(run.next_due_at, locale), "monitor-next-due")}
        </dl>
        {(run.retry_reason || errors.length > 0) && <div className="flex flex-col gap-1 text-small text-ink-2">
          {run.retry_reason && <p className="m-0 [overflow-wrap:anywhere]">{run.retry_reason}</p>}
          {errors.map(([ticker, message]) => <p key={ticker} className="m-0 [overflow-wrap:anywhere]"><span className="font-mono text-ink">{ticker}</span> · {message}</p>)}
        </div>}
        <p className="m-0 text-caption text-muted-foreground">{t("延迟阈值为")} {staleHours(status.stale_after_seconds)} {t("小时")}{locale === "en-US" ? ". " : "。"}{t("最近扫描成功只代表一条持久化记录；定时健康需观察两个实际周期。")}</p>
      </>
      : <p className="m-0 text-small text-ink-2">{t("没有实际扫描或成功记录时，页面不会把每小时计划显示为健康。")}</p>}
  </section>;
}
