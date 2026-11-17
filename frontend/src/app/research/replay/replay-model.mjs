import { jobFailurePhrase } from "../../../forecast-model.mjs";

// The historical replay page's pure rules (P6.4): the form's defaults and checks, the list of replays, and the words for evaluations and a failed job.  They are the old
// page's (HistoricalReplayWorkspace.tsx), moved here so the page and the checks read one copy.

/** A date as the form writes it: the reader's local calendar day, YYYY-MM-DD. */
export function localDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** The decision day the form starts on: 32 days back, moved earlier to a weekday (the old page's default; a long holiday may need an earlier day by hand). */
export function defaultReplayDate(now = new Date()) {
  const date = new Date(now);
  date.setDate(date.getDate() - 32);
  while (date.getDay() === 0 || date.getDay() === 6) date.setDate(date.getDate() - 1);
  return localDate(date);
}

/**
 * The form's checks, as the old form had them (a required field and a `max` of today on the date input): a company, and a decision day that is set and not after
 * today.  Whether the day is a closed XNYS session with its 20 sessions after it is the server's to say (the old page did not check it either).
 */
export function validateReplayForm({ symbol, date }, today) {
  if (!String(symbol ?? "").trim()) return { ok: false, field: "symbol", phrase: "请选择股票" };
  if (!date) return { ok: false, field: "date", phrase: "请选择历史决策日" };
  if (date > today) return { ok: false, field: "date", phrase: "历史决策日不能晚于今天" };
  return { ok: true };
}

/** The replays of one company, newest decision day first: every version of the historical-research cohort. */
export function replayRows(evaluation) {
  const roots = evaluation?.cohorts?.historical_research?.roots ?? [];
  return roots.flatMap((root) => root.versions).sort((a, b) => b.decision_at.localeCompare(a.decision_at));
}

/** The words for an evaluation's status (a zh-CN phrase key) and the badge kind that goes with it (a failed evaluation is the only failure). */
export function evaluationPhrase(status) {
  return ({ pending: "等待评估", succeeded: "已完成评估", blocked_price: "行情不足", failed: "评估失败" })[status] ?? "待评估";
}
export function evaluationKind(status) {
  return status === "succeeded" ? "success" : status === "failed" ? "failure" : "neutral";
}
export function directionPhrase(direction) {
  return ({ bearish: "看跌", neutral: "中性", bullish: "看涨" })[direction] ?? direction;
}
export function modelPhrase(status) {
  return ({ research_only: "研究简报", experimental_jev: "Jev 实验模型", experimental_llm: "推理模型实验预测", experimental_joint: "联合研究模型", baseline_only: "基线模型" })[status] ?? status;
}
/** The job's status words, as the old status block wrote them. */
export function jobStatusPhrase(status) {
  return ({ queued: "等待处理", running: "正在生成", succeeded: "回放已生成", succeeded_no_change: "已有相同回放", blocked_data: "资料不足，回放未生成", failed: "回放任务失败" })[status] ?? status;
}
export const isTerminalJob = (status) => ["succeeded", "succeeded_no_change", "blocked_data", "failed"].includes(status);

/**
 * What a replay job that ended without a replay says: its status words, and the reason.  The reason is the existing failure-code table's sentence
 * (`jobFailurePhrase`); a code the table does not know is shown as it is (the old page showed every code raw).
 */
export function replayFailure(job) {
  const code = job.error?.type ?? null;
  return { title: jobStatusPhrase(job.status), code, reason: code ? jobFailurePhrase(code) : null };
}
