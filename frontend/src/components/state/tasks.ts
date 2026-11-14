import { useEffect, useState, useSyncExternalStore } from "react";
import { createTaskRegistry, type RunningTask } from "../../task-registry.mjs";
import { notify } from "./notify";

/**
 * The register of long tasks that are running (design 4.0, 长任务).  In memory: it lives as long as the page, which is what "you can
 * leave the page" needs (the task is not tied to the page that started it).  A task that ends announces itself with a toast.
 * Connecting the real long tasks (SEC scan, material analysis, forecast, replay) is the research packages' job: they call
 * `tasks.start({ label, stage })`, then `handle.setStage()` and `handle.done()` / `handle.fail()`.
 */
// Elapsed times come from the monotonic clock: the wall clock can jump, and a test may freeze it.
export const tasks = createTaskRegistry({ now: () => performance.now() });

tasks.onFinish(({ task, ok, message }) => {
  if (ok) notify.success(message || task.label);
  else notify.error(message || task.label);
});

export function useRunningTasks(): RunningTask[] {
  return useSyncExternalStore(tasks.subscribe, tasks.getSnapshot, tasks.getSnapshot);
}

/** A clock that ticks every second while `active`, for the elapsed times on the bar. */
export function useSecondClock(active: boolean): number {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return;
    setNow(performance.now());
    const timer = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}
