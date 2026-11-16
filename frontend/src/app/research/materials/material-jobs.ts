import { getMaterialAnalysis, getMaterialAnalysisJob } from "../../../api/material-library";
import { translatePhrase } from "../../../i18n";
import type { MaterialAnalysisJob, MaterialAnalysisVersion, MaterialSourceType } from "../../../types";
import { tasks } from "@/components/state/tasks";
import { isActiveJobStatus, jobErrorPhrase } from "./materials-model.mjs";

/**
 * The material analyses this page session started or found running, on the task bar (design 4.0, 长任务).  A job is read every 1.4 s as the old page did (the job,
 * and the saved analysis once it succeeds), wherever the reader is: the bar shows the stage and the time, the end is a toast, and a page that is open hears
 * about it through `onSettled`.  The reads and their order are the old page's.
 */
export const MATERIAL_JOB_PREFIX = "material-analysis:";
const POLL_MS = 1400;

export type SettledMaterialJob = { job: MaterialAnalysisJob; analysis: MaterialAnalysisVersion | null; sourceType: MaterialSourceType; sourceId: string };

const running = new Map<string, number>();
const listeners = new Set<(event: SettledMaterialJob) => void>();

export const stageText = (status: string) => translatePhrase(status === "queued" ? "分析任务排队中…" : "正在分析这份材料…");
export const isFollowing = (jobId: string) => running.has(`${MATERIAL_JOB_PREFIX}${jobId}`);

/** Put a job on the task bar and follow it until it settles (a job already followed, or one that is not under way, is left alone). */
export function followMaterialJob(job: MaterialAnalysisJob, about: { sourceType: MaterialSourceType; sourceId: string; title: string }) {
  if (!job.job_id || !isActiveJobStatus(job.status)) return;
  const id = `${MATERIAL_JOB_PREFIX}${job.job_id}`;
  if (running.has(id)) return;
  const label = `${translatePhrase("分析材料")} · ${about.title}`;
  const handle = tasks.start({ id, label, stage: stageText(job.status) });
  let busy = false;
  const settle = (next: MaterialAnalysisJob, analysis: MaterialAnalysisVersion | null) => {
    window.clearInterval(running.get(id));
    running.delete(id);
    if (next.status === "succeeded") handle.done(`${translatePhrase("材料分析完成")} · ${about.title}`);
    else handle.fail(`${translatePhrase("材料分析没有完成")}：${translatePhrase(jobErrorPhrase(next.safe_error_code))} · ${about.title}`);
    for (const listener of [...listeners]) listener({ job: next, analysis, sourceType: about.sourceType, sourceId: about.sourceId });
  };
  const timer = window.setInterval(async () => {
    if (busy) return;
    busy = true;
    try {
      const next = await getMaterialAnalysisJob(job.job_id);
      if (!running.has(id)) return;
      if (isActiveJobStatus(next.status)) handle.setStage(stageText(next.status));
      else if (next.status === "succeeded" && next.analysis_id) settle(next, await getMaterialAnalysis(next.analysis_id));
      else settle(next, null);
    } catch { /* A read that fails is tried again on the next tick. */ }
    finally { busy = false; }
  }, POLL_MS);
  running.set(id, timer);
}

/** A page hears every material job that settles while it is open. */
export function onMaterialJobSettled(listener: (event: SettledMaterialJob) => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
