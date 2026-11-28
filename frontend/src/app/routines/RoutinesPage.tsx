import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { errorReason } from "@/components/state/error-message";
import { notify } from "@/components/state/notify";
import { useOpenConversation } from "../chat/ChatSessionProvider";
import { useWorkspace } from "../workspace";
import { CompanyTabs } from "../research/CompanyTabs";
import { confirmInboxItem, mintInboxCard, setInboxStatus } from "../../api/inbox-actions";
import type { AgentTask } from "../../api/tasks";
import { useLocale } from "../../i18n";
import { routinesBadge } from "../../inbox-items.mjs";
import { hashHref, paths, routinesTab } from "../../routes.mjs";
import { confirmEntries, type ConfirmEntry } from "../../routine-cards.mjs";
import { botFilter, tasksOfBot } from "../../routine-view.mjs";
import { BotFilter } from "./BotFilter";
import { ConfirmTab } from "./ConfirmTab";
import { RunsPane } from "./RunsPane";
import { WorkPane } from "./WorkPane";
import { NewTaskButton, TasksList } from "./TasksList";
import { TaskDrawer } from "./TaskDrawer";
import { useRoutinesData } from "./use-routines";
import { useTaskActions } from "./use-task-actions";

type Tab = "confirm" | "tasks" | "runs" | "work";
/** The tab an address without ?tab= opens: 待你确认, the first one and the one the sidebar's number points at (a fixed default: the page does not jump when the lists arrive). */
const DEFAULT_TAB: Tab = "confirm";

/**
 * 任务 (#/routines, design 4.10): four tabs in the address (?tab=confirm|tasks|runs|work, the last 手上的事 of design 4.8; the company page's tab list: manual activation, Enter or Space opens the one in focus).  待你确认 holds what waits for a press (the same two lists and the same count,
 * routinesBadge, as the sidebar's number), 全部任务 the task cards with the switch, 运行记录 the last runs; ?bot= narrows the last two to one bot.  New and edit are one
 * side drawer.  Every request is the old page's: the lists, PATCH / DELETE of a task, the inbox presses.
 */
export function RoutinesPage() {
  const { t } = useLocale();
  const ws = useWorkspace();
  const openConversation = useOpenConversation();
  const bots = ws.bots.bots;
  const [params, setParams] = useSearchParams();
  const tab: Tab = routinesTab(params) ?? DEFAULT_TAB;
  const filter = ws.bots.loaded ? botFilter(params.get("bot"), bots) : params.get("bot") ?? "";
  const data = useRoutinesData({ runsBotId: filter });
  const after = useCallback(async () => { await data.reloadAll(); await ws.bots.reload(); }, [data.reloadAll, ws.bots.reload]); // eslint-disable-line react-hooks/exhaustive-deps
  const actions = useTaskActions(after);

  const setQuery = (patch: Record<string, string>) => setParams(previous => {
    const next = new URLSearchParams(previous);
    for (const [key, value] of Object.entries(patch)) { if (value) next.set(key, value); else next.delete(key); }
    return next;
  }, { replace: true });

  // The lists of the 待你确认 tab follow the sidebar's number: whenever the bot list is read again (a finished answer, an action here) or the tab comes back to the front, they are read again.
  const reloadConfirm = data.proposals.reload, reloadConfirms = data.confirms.reload;
  const seen = useRef(ws.bots.bots);
  useEffect(() => { if (seen.current !== ws.bots.bots) { seen.current = ws.bots.bots; void reloadConfirm(); void reloadConfirms(); } }, [ws.bots.bots, reloadConfirm, reloadConfirms]);
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === "visible") { void reloadConfirm(); void reloadConfirms(); } };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [reloadConfirm, reloadConfirms]);

  // --- 待你确认: the old page's presses, one by one.
  const [busy, setBusy] = useState<string | null>(null);
  const entries = confirmEntries(data.proposals.data ?? [], data.confirms.data ?? []);
  const count = routinesBadge(data.proposals.data ?? [], data.confirms.data ?? []);
  async function press(entry: ConfirmEntry, value: string) {
    const action = value.split(":")[0];
    setBusy(entry.id);
    try {
      if (action === "review") {
        // A proposal's card waits in the conversation it was made in; a suggested write gets its card now, with its own ten minutes, in the conversation of the run.
        const conversation = entry.kind === "proposal" ? entry.conversationId : (await mintInboxCard(entry.id)).conversation_id;
        if (conversation) { await openConversation(conversation); ws.go("agent"); }
        return;
      }
      if (action === "open") { if (entry.conversationId) window.location.hash = hashHref(paths.chatConversation(entry.conversationId)); return; }
      if (action === "confirm" || action === "skip" || action === "later") {
        const result = await confirmInboxItem(entry.id, action, entry.token);
        if (result.ok === false) notify.error(result.message || t("没有确认成功，请到对话里核对。"), { id: `routines:press:${entry.id}` });
        else notify.success(t(action === "confirm" ? "已同意，操作已执行。" : action === "skip" ? "已跳过。" : "已放到稍后，仍在这里等你。"), { id: `routines:press:${entry.id}` });
      } else if (action === "dismiss") {
        await setInboxStatus(entry.id, "dismissed");
        notify.success(t("已忽略。"), { id: `routines:press:${entry.id}` });
      }
      await Promise.all([data.proposals.reload(), data.confirms.reload()]);
      await ws.bots.reload();
    } catch (error) {
      notify.error(errorReason(error, t), { id: `routines:press:${entry.id}` });
    } finally { setBusy(null); }
  }

  // --- the drawer
  const [drawer, setDrawer] = useState<{ open: boolean; task: AgentTask | null }>({ open: false, task: null });
  const opener = useRef<HTMLElement | null>(null);
  const newButton = useRef<HTMLDivElement>(null);
  const openDrawer = (task: AgentTask | null, from: HTMLElement | null) => { opener.current = from; setDrawer({ open: true, task }); };
  const returnFocus = () => { const back = opener.current?.isConnected ? opener.current : newButton.current?.querySelector("button"); (back as HTMLElement | null)?.focus(); };
  const defaultBotId = filter || ws.bots.defaultBot?.id || bots[0]?.id || "";
  const shownTasks = tasksOfBot(data.tasks.data, filter);
  const confirmError = data.proposals.error ?? data.confirms.error;

  return <main data-testid="routines-page" aria-labelledby="routines-title" className="mx-auto flex w-full min-w-0 max-w-[1100px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 id="routines-title" className="text-title-m text-ink">{t("任务")}</h1>
        <p className="max-w-2xl text-small text-muted-foreground">{t("按时间自动运行的简报与提醒，以及等你点头的事。")}</p>
      </div>
      <div ref={newButton}><NewTaskButton onClick={() => openDrawer(null, document.activeElement instanceof HTMLElement ? document.activeElement : null)} /></div>
    </header>
    <CompanyTabs label={t("任务页签")} value={tab} onChange={value => setQuery({ tab: value })} tabs={[
      { value: "confirm", testId: "tab-confirm", label: <span className="inline-flex items-center gap-1.5">{t("待你确认")}{count > 0 && <span data-testid="tab-confirm-count" className="rounded-full bg-action-soft px-1.5 font-mono text-caption text-action">{count}</span>}</span> },
      { value: "tasks", testId: "tab-tasks", label: t("全部任务") },
      { value: "runs", testId: "tab-runs", label: t("运行记录") },
      { value: "work", testId: "tab-work", label: t("手上的事") },
    ]}>
      {tab === "confirm" && <ConfirmTab entries={entries} bots={bots} busy={busy} onPress={press} loading={data.proposals.loading || data.confirms.loading} error={confirmError}
        onRetry={() => { void data.proposals.reload(); void data.confirms.reload(); }} />}
      {tab === "tasks" && <div className="flex min-w-0 flex-col gap-3">
        <BotFilter bots={bots} value={filter} onChange={botId => setQuery({ bot: botId })} />
        <TasksList tasks={data.tasks.data ? shownTasks : null} error={data.tasks.error} loading={data.tasks.loading} onRetry={() => void data.tasks.reload()} bots={bots} actions={actions}
          onEdit={(task, from) => openDrawer(task, from)} onNew={() => openDrawer(null, document.activeElement instanceof HTMLElement ? document.activeElement : null)} emptyTitle={filter ? t("这个 bot 还没有任务。") : undefined} />
      </div>}
      {tab === "runs" && <div className="flex min-w-0 flex-col gap-3">
        <BotFilter bots={bots} value={filter} onChange={botId => setQuery({ bot: botId })} />
        <RunsPane runs={data.runs.data} error={data.runs.error} loading={data.runs.loading} onRetry={() => void data.runs.reload()} />
      </div>}
      {tab === "work" && <WorkPane />}
    </CompanyTabs>
    <TaskDrawer open={drawer.open} onOpenChange={open => setDrawer(current => ({ ...current, open }))} task={drawer.task} bots={bots} defaultBotId={defaultBotId} returnFocus={returnFocus}
      onSaved={() => void after()} />
  </main>;
}
