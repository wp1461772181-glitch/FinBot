import { useSyncExternalStore } from "react";
import { getV2Job } from "../../../api/forecast-v2";
import { jobFailurePhrase } from "../../../forecast-model.mjs";
import { translatePhrase } from "../../../i18n";
import type { V2ForecastJob } from "../../../types";
import { tasks } from "@/components/state/tasks";

/**
 * The forecast jobs of this page session, on the task bar (design 4.0, 长任务).  A job that was started is polled every 3 s, wherever the reader is: the
 * bar shows its stage and elapsed time, the end is a toast, and a page that is still open hears about it through `onSettled`.  A job that did not
 * make a version is kept as a failure (with its reason) until the reader dismisses it or retries; the retry is the old one: the same request again.
 */
export const JOB_TASK_PREFIX = "forecast-job:";
const POLL_MS = 3_000;

export type JobFailure = { id: string; symbol: string; kind: V2ForecastJob["kind"]; phrase: string; code: string | null };

let failures: ReadonlyArray<JobFailure> = [];
const listeners = new Set<() => void>();
const settledListeners = new Set<(job: V2ForecastJob) => void>();
const running = new Map<string, number>();
const publish = () => { for (const listener of [...listeners]) listener(); };

export function isActiveJob(job: V2ForecastJob | null | undefined) {
  return job?.status === "queued" || job?.status === "running";
}

function savedJobKey(symbol: string) { return `market-evidence-agent:v2-job:${symbol}`; }
/** The last job id per company is kept in the browser (as the old page did); the job itself stays durable on the server. */
function rememberJob(symbol: string, job: V2ForecastJob) {
  try { window.localStorage.setItem(savedJobKey(symbol), job.id); } catch { /* Storage is optional. */ }
}

export function jobStageText(job: V2ForecastJob) {
  if (job.status === "queued") return translatePhrase("已排队，等待处理");
  return translatePhrase(job.current_stage || "正在处理");
}

/** What a settled job says in words: the outcome, and for one that made no version the reason (a phrase the failure table owns, else the code). */
export function jobOutcome(job: V2ForecastJob): { ok: boolean; phrase: string } {
  if (job.status === "succeeded") return { ok: true, phrase: translatePhrase("已生成预测版本") };
  if (job.status === "succeeded_no_change") return { ok: true, phrase: translatePhrase("已完成，但输入没有产生新版本") };
  const code = job.error?.type;
  const reason = jobFailurePhrase(code) ?? null;
  const detail = reason ? translatePhrase(reason) : `${translatePhrase("任务未完成（")}${code}${translatePhrase("），没有发布预测版本。")}`;
  return { ok: false, phrase: `${translatePhrase(job.status === "blocked_data" ? "未生成预测：" : "处理未完成：")}${detail}` };
}

/** Put a started job on the task bar and follow it until it settles. */
export function followJob(job: V2ForecastJob, label: string) {
  rememberJob(job.symbol, job);
  const id = `${JOB_TASK_PREFIX}${job.id}`;
  if (running.has(id)) return;
  const handle = tasks.start({ id, label, stage: jobStageText(job) });
  const settle = (next: V2ForecastJob) => {
    window.clearInterval(running.get(id));
    running.delete(id);
    const outcome = jobOutcome(next);
    if (outcome.ok) handle.done(outcome.phrase);
    else {
      failures = [...failures.filter((item) => item.id !== next.id), { id: next.id, symbol: next.symbol, kind: next.kind, phrase: outcome.phrase, code: next.error?.type ?? null }];
      publish();
      handle.fail(outcome.phrase);
    }
    for (const listener of [...settledListeners]) listener(next);
  };
  if (!isActiveJob(job)) { settle(job); return; }
  const timer = window.setInterval(() => {
    getV2Job(job.id)
      .then((next) => { if (!running.has(id)) return; if (isActiveJob(next)) handle.setStage(jobStageText(next)); else settle(next); })
      .catch(() => { /* A poll that fails is tried again on the next tick. */ });
  }, POLL_MS);
  running.set(id, timer);
}

/** A page hears every job that settles while it is open. */
export function onJobSettled(listener: (job: V2ForecastJob) => void) {
  settledListeners.add(listener);
  return () => { settledListeners.delete(listener); };
}

export function dismissFailure(id: string) {
  failures = failures.filter((item) => item.id !== id);
  publish();
}

const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export function useJobFailures() {
  return useSyncExternalStore(subscribe, () => failures, () => failures);
}
