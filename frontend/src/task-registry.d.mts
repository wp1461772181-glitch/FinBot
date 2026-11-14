export type RunningTask = { id: string; label: string; stage: string; startedAt: number };
export type TaskFinish = { task: RunningTask; ok: boolean; message: string; elapsedMs: number };
export type TaskHandle = { id: string; setStage(stage: string): void; done(message?: string): void; fail(message?: string): void };
export type TaskRegistry = {
  start(task: { id?: string; label: string; stage?: string }): TaskHandle;
  finish(id: string, result?: { ok?: boolean; message?: string }): void;
  getSnapshot(): RunningTask[];
  subscribe(listener: () => void): () => void;
  onFinish(listener: (event: TaskFinish) => void): () => void;
  elapsedMs(task: RunningTask): number;
};
export function createTaskRegistry(options?: { now?: () => number }): TaskRegistry;
export function formatElapsed(ms: number): string;
