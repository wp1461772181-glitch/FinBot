import { StatusBadge } from "@/components/StatusBadge";
import { Timeline, type TimelineItem } from "@/components/Timeline";
import type { V2MonitorStatus } from "../../../types";
import { formatDateTime, translatePhrase, useLocale } from "../../../i18n";
import { RUN_STATUS_PHRASE, runMoments } from "./monitor-model.mjs";

/** The recent runs (design 4.8, the shared Timeline): the last run, and the last fully successful one when that is another run.  The server keeps those two records. */
export function RunTimeline({ status }: { status: V2MonitorStatus }) {
  const { t, locale } = useLocale();
  const at = (value: string | null) => (value ? formatDateTime(value, locale, "UTC") : "—");
  const moments = runMoments(status);
  const items: TimelineItem[] = moments.map(moment => ({
    id: moment.id,
    title: moment.kind === "run" ? t("最近运行") : t("最近全成功"),
    marks: <StatusBadge kind={moment.status === "succeeded" ? "success" : moment.status === "running" ? "progress" : "failure"} className="h-5">{translatePhrase(RUN_STATUS_PHRASE[moment.status])}</StatusBadge>,
    meta: moment.kind === "run"
      ? <>{t("检查开始")} {at(moment.startedAt)} · {t("完成")} {at(moment.completedAt)} · {t("下一次预期")} {at(moment.nextDueAt)}{moment.alsoLastSuccess && <> · {t("最近全成功")}</>}</>
      : <>{t("完成")} {at(moment.completedAt)}</>,
  }));
  return <section data-testid="monitor-runs" aria-labelledby="monitor-runs-title" className="flex min-w-0 flex-col gap-3">
    <h2 id="monitor-runs-title" className="text-title-s text-ink">{t("最近运行")}</h2>
    {items.length ? <Timeline items={items} label={t("最近运行")} /> : <p className="m-0 text-small text-muted-foreground">{t("没有运行记录")}</p>}
  </section>;
}
