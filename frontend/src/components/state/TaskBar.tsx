import { LoaderCircle } from "lucide-react";
import { useLocale } from "../../i18n";
import { formatElapsed } from "../../task-registry.mjs";
import { tasks, useRunningTasks, useSecondClock } from "./tasks";

/** One line of the bar: what is running, the stage it is in, the time it has taken.  The stage is announced when it changes; the time is not (it would speak every second). */
export function TaskRow({ label, stage, elapsedMs }: { label: string; stage?: string; elapsedMs: number }) {
  const { t } = useLocale();
  const elapsed = formatElapsed(elapsedMs);
  return <li data-slot="task-row" className="flex items-center gap-3 rounded-md border border-line bg-surface px-3 py-2 text-small shadow-sm">
    <LoaderCircle aria-hidden="true" className="size-4 shrink-0 text-brand motion-safe:animate-spin" />
    <span className="min-w-0 flex-1 truncate"><span className="font-medium text-ink">{label}</span>{stage && <span role="status" className="text-muted-foreground"> · {stage}</span>}</span>
    <span className="shrink-0 font-mono text-caption text-muted-foreground" data-elapsed="" aria-label={`${t("已用时")} ${elapsed}`}>{elapsed}</span>
  </li>;
}

/**
 * 「任务条」 (design 4.0, 长任务): the stage a long task is in and how long it has run.  The reader can leave the page; the bar
 * stays (the register is not the page's), and the end of the task comes as a toast.  One line per running task.
 */
export function TaskBar({ className = "" }: { className?: string }) {
  const { t } = useLocale();
  const running = useRunningTasks();
  const now = useSecondClock(running.length > 0);
  if (!running.length) return null;
  return <ul data-slot="task-bar" aria-label={t("进行中的任务")} className={`flex flex-col gap-1 ${className}`}>
    {running.map((task) => <TaskRow key={task.id} label={task.label} stage={task.stage} elapsedMs={Math.max(0, now - task.startedAt)} />)}
  </ul>;
}

export { tasks };
