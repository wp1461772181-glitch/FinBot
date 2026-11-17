import { useSyncExternalStore } from "react";
import { getV2Job } from "../../../api/forecast-v2";
import { translatePhrase } from "../../../i18n";
import type { V2ForecastJob } from "../../../types";
import { tasks } from "@/components/state/tasks";
import { isTerminalJob, jobStatusPhrase } from "./replay-model.mjs";

/**
 * The historical replays this page session started, on the task bar (design 4.0, 长任务).  A job is read at once and then every 2 s, as the old page did, wherever the
 * reader is: the bar shows the stage and the time, the end is a toast, and a page that is open hears about it through `onReplaySettled`.  A job that ends without a replay
 * is kept (with its reason) until the reader dismisses it; the replay jobs have a store of their own so they never show up as a forecast job's failure (whose retry makes a forecast).
 */
export const REPLAY_JOB_PREFIX = "replay-job:";
const POLL_MS = 2_000;

const running = new Map<string, number>();
const settledListeners = new Set<(job: V2ForecastJob) => void>();
const storeListeners = new Set<() => void>();
let failure: V2ForecastJob | null = null;
const publish = () => { for (const listener of [...storeListeners]) listener(); };

export const replayStage = (job: V2ForecastJob) => translatePhrase(job.status === "queued" ? "等待处理" : jobStatusPhrase("running"));
export const isReplayRunning = () => running.size > 0;

/** Put a started replay job on the task bar and follow it until it ends. */
export function followReplayJob(job: V2ForecastJob, label: string) {
  const id = `${REPLAY_JOB_PREFIX}${job.id}`;
  if (running.has(id)) return;
  failure = null;
  const handle = tasks.start({ id, label, stage: replayStage(job) });
  running.set(id, 0);
  publish();
  const settle = (next: V2ForecastJob) => {
    window.clearTimeout(running.get(id));
    running.delete(id);
    if (next.status === "failed" || next.status === "blocked_data") { failure = next; handle.fail(`${translatePhrase(jobStatusPhrase(next.status))} · ${label}`); }
    else handle.done(`${translatePhrase(jobStatusPhrase(next.status))} · ${label}`);
    publish();
    for (const listener of [...settledListeners]) listener(next);
  };
  const tick = async () => {
    try {
      const next = await getV2Job(job.id);
      if (!running.has(id)) return;
      if (isTerminalJob(next.status)) { settle(next); return; }
      handle.setStage(replayStage(next));
    } catch { /* A read that fails is tried again on the next tick: the job is durable. */ }
    if (running.has(id)) running.set(id, window.setTimeout(tick, POLL_MS));
  };
  running.set(id, window.setTimeout(tick, 0));
}

/** A page hears every replay job that ends while it is open. */
export function onReplaySettled(listener: (job: V2ForecastJob) => void) {
  settledListeners.add(listener);
  return () => { settledListeners.delete(listener); };
}

export function dismissReplayFailure() { failure = null; publish(); }

const subscribe = (notify: () => void) => { storeListeners.add(notify); return () => { storeListeners.delete(notify); }; };
/** The replay job that ended without a replay, until it is dismissed (or another replay starts). */
export const useReplayFailure = () => useSyncExternalStore(subscribe, () => failure, () => null);
/** Whether a replay job is under way (the form's 生成 waits for it, as the old one did). */
export const useReplayRunning = () => useSyncExternalStore(subscribe, () => running.size > 0, () => false);
