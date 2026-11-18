import { StatusBadge } from "@/components/StatusBadge";
import { Timeline, type TimelineItem } from "@/components/Timeline";
import type { TaskRun } from "../../api/tasks";
import { useLocale } from "../../i18n";
import { hashHref, paths } from "../../routes.mjs";
import { statusKind } from "../../routine-view.mjs";

/**
 * The last runs as a timeline (design 4.10, 5.3): the task's name, when, how it went (the server's words in a badge of its tone), whether the result was posted into the
 * conversation, and 打开过程, which opens that conversation.  The order is the server's: newest first.
 */
export function RunsTimeline({ runs, label }: { runs: TaskRun[]; label: string }) {
  const { t } = useLocale();
  const items: TimelineItem[] = runs.map(run => ({
    id: run.id,
    title: <span data-testid="run-title">{run.task_name}</span>,
    marks: <span data-testid="run-status" data-tone={statusKind(run.status)}><StatusBadge kind={statusKind(run.status)} className="h-5">{run.status_label}</StatusBadge></span>,
    meta: <span data-testid="run-meta">{run.created_at ? <span className="font-mono">{new Date(run.created_at).toLocaleString()}</span> : null}{run.posted > 0 ? ` · ${t("已贴进对话")}` : ""}{run.conversation_id && <> · <a href={hashHref(paths.chatConversation(run.conversation_id))} data-testid="run-open" className="rounded-sm text-brand underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">{t("打开过程")}</a></>}</span>,
  }));
  return <Timeline items={items} label={label} className="rounded-md border border-line bg-surface p-4" />;
}
