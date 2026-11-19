import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import type { Bot } from "../../api/bots";
import type { AgentTask } from "../../api/tasks";
import { useLocale } from "../../i18n";
import { TaskCard } from "./TaskCard";
import { useTaskActions } from "./use-task-actions";

/**
 * The list of task cards with its own states: the skeleton while it is read, the error bar with 重试 (the list stays when a later read fails), the empty sentence with
 * the way to make the first one.  Used by the 全部任务 tab and by a bot's settings page (`showBot` false there: the page is the bot).
 */
export function TasksList({ tasks, error, loading, onRetry, bots, showBot = true, actions, onEdit, onNew, emptyTitle }: {
  tasks: AgentTask[] | null; error: unknown; loading: boolean; onRetry: () => void; bots: Bot[]; showBot?: boolean;
  actions: ReturnType<typeof useTaskActions>; onEdit: (task: AgentTask, opener: HTMLElement | null) => void; onNew: () => void; emptyTitle?: string;
}) {
  const { t } = useLocale();
  return <div data-testid="tasks-list" className="flex min-w-0 flex-col gap-3">
    {error != null && <ErrorBar error={error} onRetry={onRetry} retrying={loading} />}
    {!tasks && loading && <DelayedSkeleton><div role="status" aria-busy="true" data-testid="tasks-skeleton" className="flex flex-col gap-3"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2].map(i => <Skeleton key={i} className="h-28 w-full" />)}</div></DelayedSkeleton>}
    {tasks && tasks.length === 0 && <div data-testid="tasks-empty" className="rounded-md border border-line bg-surface">
      <EmptyState title={emptyTitle ?? t("还没有任务。")} description={t("简报任务让 bot 按时回答一段说明；提醒任务盯着新申报、新闻线索和价格线。")} action={{ label: t("新建任务"), onClick: onNew }} />
    </div>}
    {tasks && tasks.length > 0 && <ul className="m-0 flex list-none flex-col gap-3 p-0">
      {tasks.map(task => <li key={task.id}>
        <TaskCard task={task} bot={bots.find(bot => bot.id === task.bot_id)} showBot={showBot} enabled={actions.flipped[task.id] ?? task.enabled} busy={actions.busy === task.id}
          onToggle={enabled => void actions.toggle(task, enabled)} onEdit={opener => onEdit(task, opener)} onDelete={opener => void actions.remove(task, opener)} />
      </li>)}
    </ul>}
  </div>;
}

/** 新建任务, the main button of the page's title row and of a bot's section. */
export function NewTaskButton({ onClick, disabled, className = "" }: { onClick: () => void; disabled?: boolean; className?: string }) {
  const { t } = useLocale();
  return <Button type="button" data-testid="task-new" disabled={disabled} className={`max-sm:h-11 ${className}`} onClick={onClick}><Plus aria-hidden="true" />{t("新建任务")}</Button>;
}
