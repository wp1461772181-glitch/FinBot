// What the task page says about a task or a run, apart from how it looks.  Pure, so a node test holds it.

import { runsLabel, scheduleLabel } from "./inbox-items.mjs";

/** The badge kind of a run's or a task's last outcome (agent_tasks.py STATUS_LABELS): success, failure (a run that did not happen or did not finish), in progress, or plain. */
export function statusKind(status) {
  if (status === "ok" || status === "quiet") return "success";
  if (status === "failed" || String(status ?? "").startsWith("skipped_")) return "failure";
  if (status === "running") return "progress";
  return "neutral";
}

/** "工作日 08:30 · 共 8 次"; the old list's words.  The time zone is its own item. */
export function scheduleSummary(task) {
  return [scheduleLabel(task), runsLabel(task)].filter(Boolean).join(" · ");
}

/** What a task's state is when it is not simply running: 已暂停 / 已完成 (null otherwise).  `enabled` is the switch as it is shown (it leads the server's answer for a moment after a flip). */
export function taskState(task, enabled = task?.enabled) {
  if (task?.finished) return "finished";
  return enabled ? null : "paused";
}

/** Tasks of one bot (all of them when `botId` is empty), the order the server gave them. */
export function tasksOfBot(tasks, botId) {
  return (Array.isArray(tasks) ? tasks : []).filter((task) => !botId || task.bot_id === botId);
}

/** The runs of the tasks of one bot: the server filters by bot when asked, so this only serves a list already read for every bot. */
export function runsOfBot(runs, tasks, botId) {
  if (!botId) return Array.isArray(runs) ? runs : [];
  const ids = new Set(tasksOfBot(tasks, botId).map((task) => task.id));
  return (Array.isArray(runs) ? runs : []).filter((run) => ids.has(run.task_id));
}

/** A bot id from ?bot= that is one of the bots, else "" (no filter). */
export function botFilter(value, bots) {
  return Array.isArray(bots) && bots.some((bot) => bot.id === value) ? value : "";
}
