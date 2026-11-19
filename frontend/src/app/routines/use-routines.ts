import { useCallback, useEffect, useRef, useState } from "react";
import { listAgentTasks, listTaskRuns, type AgentTask, type TaskRun } from "../../api/tasks";
import { listInbox, listTaskProposals, type InboxItem, type TaskProposal } from "../../api/inbox";

export type Read<T> = { data: T | null; error: unknown; loading: boolean; reload: () => Promise<void> };

/**
 * One list as a page holds it: `data` stays on screen while it is read again (after a write, or 重试) and a read that fails leaves the last good `data` with the
 * `error` beside it, so a refresh that fails never blanks the list.  `reload` never rejects.  Not read at all while `enabled` is false.
 */
function useRead<T>(read: (signal: AbortSignal) => Promise<T>, key: string, enabled = true): Read<T> {
  const [state, setState] = useState<{ data: T | null; error: unknown; loading: boolean }>({ data: null, error: null, loading: enabled });
  const controller = useRef<AbortController | null>(null);
  const latest = useRef(read);
  latest.current = read;
  const reload = useCallback(async () => {
    controller.current?.abort();
    const mine = new AbortController();
    controller.current = mine;
    setState(previous => ({ ...previous, loading: true }));
    try {
      const data = await latest.current(mine.signal);
      if (!mine.signal.aborted) setState({ data, error: null, loading: false });
    } catch (error) {
      if (!mine.signal.aborted) setState(previous => ({ ...previous, error, loading: false }));
    }
  }, []);
  useEffect(() => {
    if (!enabled) { setState({ data: null, error: null, loading: false }); return; }
    void reload();
    return () => controller.current?.abort();
  }, [reload, key, enabled]);
  return { ...state, reload };
}

/**
 * The four lists of the task page, each with its own state (a tab shows its own skeleton, its own error and its own empty sentence): the tasks and the last 20
 * runs (of one bot when `botId` is given: the settings page's section; the page's own bot filter narrows the runs only, `runsBotId`, since the list of tasks is cut to it on the page), the routine cards bots proposed and the writes unattended runs suggested (the
 * 待你确认 tab; the settings page does not read them).  The two the tab is made of are the two the sidebar's number is made of (useRoutinesBadge).
 */
export function useRoutinesData({ botId = "", runsBotId = botId, withConfirm = true }: { botId?: string; runsBotId?: string; withConfirm?: boolean } = {}) {
  const tasks = useRead<AgentTask[]>(signal => listAgentTasks(signal, botId || undefined), `tasks:${botId}`);
  const runs = useRead<TaskRun[]>(signal => listTaskRuns(runsBotId || undefined, signal), `runs:${runsBotId}`);
  const proposals = useRead<TaskProposal[]>(signal => listTaskProposals(signal), "proposals", withConfirm);
  const confirms = useRead<InboxItem[]>(signal => listInbox("confirm", signal), "confirms", withConfirm);
  const reloadAll = useCallback(() => Promise.all([tasks.reload(), runs.reload(), ...(withConfirm ? [proposals.reload(), confirms.reload()] : [])]).then(() => undefined), [tasks.reload, runs.reload, proposals.reload, confirms.reload, withConfirm]);
  return { tasks, runs, proposals, confirms, reloadAll };
}
