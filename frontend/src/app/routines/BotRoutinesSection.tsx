import { useCallback, useRef, useState } from "react";
import { TasksList, NewTaskButton } from "./TasksList";
import { RunsPane } from "./RunsPane";
import { TaskDrawer } from "./TaskDrawer";
import { useRoutinesData } from "./use-routines";
import { useTaskActions } from "./use-task-actions";
import type { Bot } from "../../api/bots";
import type { AgentTask } from "../../api/tasks";
import { useLocale } from "../../i18n";

/**
 * 例行任务 on a bot's settings page (design 3.4): this bot's task cards (the same list as the task page, cut to the bot) and its last 20 runs; 新建 and 编辑 are the task
 * page's drawer with the bot fixed.  Every change is saved as it is made (no save bar); `onChanged` tells the app the bot list may have moved (the sidebar's number).
 */
export function BotRoutinesSection({ bot, onChanged }: { bot: Bot; onChanged?: () => void }) {
  const { t } = useLocale();
  const data = useRoutinesData({ botId: bot.id, withConfirm: false });
  const after = useCallback(async () => { await data.reloadAll(); onChanged?.(); }, [data.reloadAll, onChanged]); // eslint-disable-line react-hooks/exhaustive-deps
  const actions = useTaskActions(after);
  const [drawer, setDrawer] = useState<{ open: boolean; task: AgentTask | null }>({ open: false, task: null });
  const opener = useRef<HTMLElement | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const openDrawer = (task: AgentTask | null, from: HTMLElement | null) => { opener.current = from; setDrawer({ open: true, task }); };
  const returnFocus = () => { const back = opener.current?.isConnected ? opener.current : root.current?.querySelector<HTMLElement>("[data-testid=task-new]"); back?.focus(); };
  return <div ref={root} data-testid="bot-routines" className="flex min-w-0 flex-col gap-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="max-w-xl text-small text-muted-foreground">{t("任务按时运行；睡眠期间错过的会在醒来后补跑一次。简报类任务需要在设置里配置后台任务模型；提醒类任务不调用模型。")}</p>
      <NewTaskButton onClick={() => openDrawer(null, document.activeElement instanceof HTMLElement ? document.activeElement : null)} />
    </div>
    <TasksList tasks={data.tasks.data} error={data.tasks.error} loading={data.tasks.loading} onRetry={() => void data.tasks.reload()} bots={[bot]} showBot={false} actions={actions}
      onEdit={(task, from) => openDrawer(task, from)} onNew={() => openDrawer(null, document.activeElement instanceof HTMLElement ? document.activeElement : null)} />
    <section aria-labelledby="bot-runs-title" className="flex flex-col gap-2">
      <h3 id="bot-runs-title" className="text-body font-medium text-ink">{t("最近 20 次运行")}</h3>
      <RunsPane runs={data.runs.data} error={data.runs.error} loading={data.runs.loading} onRetry={() => void data.runs.reload()} />
    </section>
    <TaskDrawer open={drawer.open} onOpenChange={open => setDrawer(current => ({ ...current, open }))} task={drawer.task} bots={[bot]} lockedBotId={bot.id} defaultBotId={bot.id} returnFocus={returnFocus} onSaved={() => void after()} />
  </div>;
}
