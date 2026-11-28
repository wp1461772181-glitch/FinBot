import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { Timeline, type TimelineItem } from "@/components/Timeline";
import { getWork, type WorkItem } from "../../api/work";
import { useLocale } from "../../i18n";
import { hashHref, paths } from "../../routes.mjs";
import { workStatusKind, workWhen } from "../../routine-view.mjs";
import { useLoad } from "../use-load";

/**
 * 手上的事 (design 4.8 / section 11): what it is doing for him and what it did lately, the same list the kernel's list_work reads — chat turns (running, or failed and
 * stopped within a day), routines, jobs started from a card, archive builds, memory work.  Each with its state in the server's words, when, why a failed one failed,
 * and 打开对话 when it belongs to a conversation.  Read again with 刷新; nothing here changes anything.
 */
export function WorkPane() {
  const { t } = useLocale();
  const work = useLoad(signal => getWork(signal));
  const items = work.data;
  const rows: TimelineItem[] = (items ?? []).map((item: WorkItem) => ({
    id: `${item.kind}:${item.id}`,
    title: <span data-testid="work-title">{item.title}</span>,
    marks: <span data-testid="work-status" data-tone={workStatusKind(item.status)}><StatusBadge kind={workStatusKind(item.status)} className="h-5">{t(item.status_label)}</StatusBadge></span>,
    meta: <span data-testid="work-meta" className="flex flex-col gap-0.5">
      <span><span className="font-mono">{workWhen(item, t)}</span>{item.conversation_id && <>{workWhen(item, t) ? " · " : ""}<a href={hashHref(paths.chatConversation(item.conversation_id))} data-testid="work-open" className="rounded-sm text-brand underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("打开对话")}</a></>}</span>
      {item.failure && <span data-testid="work-failure" className="text-muted-foreground">{item.failure}</span>}
    </span>,
  }));
  return <div data-testid="work-pane" className="flex min-w-0 flex-col gap-3">
    <div className="flex items-center justify-between gap-2">
      <p className="text-small text-muted-foreground">{t("它正在做的、等着做的和最近一天做完的事。也可以在对话里直接问「你手上有什么事」。")}</p>
      <button type="button" data-testid="work-reload" onClick={() => void work.reload()} disabled={work.loading} className="shrink-0 rounded-sm text-small text-brand underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">{t("刷新")}</button>
    </div>
    {work.error != null && <ErrorBar error={work.error} onRetry={() => void work.reload()} retrying={work.loading} />}
    {!items && work.loading && <DelayedSkeleton><div role="status" aria-busy="true" data-testid="work-skeleton" className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2].map(i => <Skeleton key={i} className="h-10 w-full" />)}</div></DelayedSkeleton>}
    {items && items.length === 0 && <div data-testid="work-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("现在手上没有事。")} description={t("它在回答、跑例行任务或处理你交办的事时，会列在这里。")} /></div>}
    {items && items.length > 0 && <Timeline items={rows} label={t("手上的事")} className="rounded-md border border-line bg-surface p-4" />}
  </div>;
}
