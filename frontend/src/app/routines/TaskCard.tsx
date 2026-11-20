import { useRef } from "react";
import { Ellipsis, SquarePen, Trash2 } from "lucide-react";
import { BotAvatar } from "@/components/bot/BotAvatar";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { StatusBadge } from "@/components/StatusBadge";
import type { Bot } from "../../api/bots";
import type { AgentTask } from "../../api/tasks";
import { useLocale } from "../../i18n";
import { scheduleSummary, statusKind, taskState } from "../../routine-view.mjs";

/**
 * One task (design 4.10): its name, bot (with the avatar), kind, schedule, next run, last result, how often it ran; the switch on the right saves as it is flipped, and 「…」
 * has 编辑 and 删除.  `bot` is undefined for a task whose bot is gone; `showBot` is false on a bot's own settings page (the bot is the page).
 */
export function TaskCard({ task, bot, showBot = true, enabled, busy, onToggle, onEdit, onDelete }: {
  task: AgentTask; bot: Bot | undefined; showBot?: boolean; enabled: boolean; busy: boolean;
  onToggle: (enabled: boolean) => void; onEdit: (opener: HTMLElement | null) => void; onDelete: (opener: HTMLElement | null) => void;
}) {
  const { t, locale } = useLocale();
  const menu = useRef<HTMLButtonElement>(null);
  // An item that opens a drawer or a question must not have the menu hand the focus back to its button as it closes (it would land outside the layer that just opened).
  const opening = useRef(false);
  const state = taskState(task, enabled);
  const result = task.last_status_label;
  return <article data-testid="task-card" data-task={task.id} data-enabled={enabled ? "true" : "false"} aria-label={task.name} className="flex min-w-0 flex-col gap-2.5 rounded-md border border-line bg-surface p-3.5">
    <div className="flex items-start gap-3">
      {showBot && <span className="mt-0.5 grid shrink-0 place-items-center">{bot ? <BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={28} /> : <span aria-hidden="true" className="size-7 rounded-full bg-sunken" />}</span>}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <h3 className="min-w-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{task.name}</h3>
          <span data-testid="task-kind" data-kind={task.kind}><StatusBadge kind="neutral" className="h-5">{t(task.kind === "brief" ? "简报" : "提醒")}</StatusBadge></span>
          {state === "paused" && <StatusBadge kind="neutral" className="h-5">{t("已暂停")}</StatusBadge>}
          {state === "finished" && <StatusBadge kind="neutral" className="h-5">{t("已完成")}</StatusBadge>}
        </div>
        <p className="text-small text-muted-foreground [overflow-wrap:anywhere]">{showBot && <>{bot?.name ?? t("已删除的 bot")} · </>}{scheduleSummary(task, locale)} · <span data-testid="task-timezone">{task.timezone}</span></p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Switch checked={enabled} disabled={busy} aria-label={`${t(enabled ? "暂停" : "启用")} ${task.name}`} data-testid="task-switch" onCheckedChange={onToggle} className="max-sm:scale-110" />
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild><Button ref={menu} type="button" variant="ghost" size="icon" disabled={busy} aria-label={`${t("更多操作")} ${task.name}`} data-testid="task-menu" className="size-9 max-sm:size-11"><Ellipsis aria-hidden="true" /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end" onCloseAutoFocus={event => { if (opening.current) { event.preventDefault(); opening.current = false; } }}>
            <DropdownMenuItem data-testid="task-edit" onSelect={() => { opening.current = true; onEdit(menu.current); }}><SquarePen aria-hidden="true" />{t("编辑")}</DropdownMenuItem>
            <DropdownMenuItem data-testid="task-delete" variant="destructive" onSelect={() => { opening.current = true; onDelete(menu.current); }}><Trash2 aria-hidden="true" />{t("删除")}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
    <dl className="m-0 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-small">
      <div className="flex items-center gap-1.5"><dt className="text-muted-foreground">{t("上次结果")}</dt><dd className="m-0">{result ? <span data-testid="task-result" data-tone={statusKind(task.last_status)}><StatusBadge kind={statusKind(task.last_status)} className="h-5">{t(result)}</StatusBadge></span> : <span className="text-muted-foreground" data-testid="task-result">{t("尚未运行")}</span>}</dd></div>
      {enabled && task.next_run_at && <div className="flex items-center gap-1.5"><dt className="text-muted-foreground">{t("下次运行")}</dt><dd className="m-0 font-mono text-ink-2" data-testid="task-next">{new Date(task.next_run_at).toLocaleString()}</dd></div>}
      <div className="flex items-center gap-1.5"><dt className="text-muted-foreground">{t("已执行")}</dt><dd className="m-0 font-mono text-ink-2">{task.runs_done} {t("次")}</dd></div>
    </dl>
    {task.instruction && <blockquote className="m-0 line-clamp-2 border-l-2 border-line-strong pl-3 text-small text-ink-2">“{task.instruction}”</blockquote>}
  </article>;
}
