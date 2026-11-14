// The register of tasks that are running (design 4.0, 长任务): a stage name and the time since it started, kept in memory so
// the bar survives a page change.  Pure: the clock is passed in; the bar and the toast that announces a finish are components.
// Connecting the real long tasks (SEC scan, material analysis, forecast, replay) is a later package: they call `start`.

export function createTaskRegistry({ now = () => Date.now() } = {}) {
  let tasks = [];                     // running, oldest first
  let snapshot = tasks;
  const listeners = new Set();
  const finishListeners = new Set();
  let counter = 0;
  const publish = () => { snapshot = tasks; for (const listener of [...listeners]) listener(); };
  return {
    /** Register a running task.  Returns its handle. */
    start({ id, label, stage = "" }) {
      const key = id ?? `task-${(counter += 1)}`;
      const existing = tasks.find((task) => task.id === key);
      if (existing) { tasks = tasks.map((task) => task.id === key ? { ...task, label, stage } : task); publish(); }
      else { tasks = [...tasks, { id: key, label, stage, startedAt: now() }]; publish(); }
      return {
        id: key,
        setStage: (next) => { tasks = tasks.map((task) => task.id === key ? { ...task, stage: next } : task); publish(); },
        done: (message) => this.finish(key, { ok: true, message }),
        fail: (message) => this.finish(key, { ok: false, message }),
      };
    },
    /** A task ended.  Unknown ids are ignored (a finish can arrive twice).  Finish listeners get { task, ok, message, elapsedMs }. */
    finish(id, { ok = true, message = "" } = {}) {
      const task = tasks.find((item) => item.id === id);
      if (!task) return;
      tasks = tasks.filter((item) => item.id !== id);
      publish();
      const event = { task, ok, message, elapsedMs: Math.max(0, now() - task.startedAt) };
      for (const listener of [...finishListeners]) listener(event);
    },
    /** The running tasks; the same array until something changes. */
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    onFinish(listener) { finishListeners.add(listener); return () => finishListeners.delete(listener); },
    elapsedMs: (task) => Math.max(0, now() - task.startedAt),
  };
}

/** "0:07", "1:05", "1:02:03": the elapsed time as the bar shows it. */
export function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const seconds = total % 60, minutes = Math.floor(total / 60) % 60, hours = Math.floor(total / 3600);
  const two = (value) => String(value).padStart(2, "0");
  return hours ? `${hours}:${two(minutes)}:${two(seconds)}` : `${minutes}:${two(seconds)}`;
}
