// A routine task's result, and the end message of a job started from a card, are posted into a line as a turn whose user row is a system head,
// not the owner's words.

export const TASK_POST_PREFIX = "【例行任务结果】";
export const JOB_POST_PREFIX = "【任务结果】";
const HEAD = /^(?:【例行任务结果】|【任务结果】)「(.+?)」\s*(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)?/;

/** True when a user row is the system head of a posted task result (a routine's, or a card job's). */
export function isTaskPostHead(content) {
  const text = String(content ?? "");
  return text.startsWith(TASK_POST_PREFIX) || text.startsWith(JOB_POST_PREFIX);
}

/** "routine" for a routine's result, "job" for the end of a job started from a card, null for any other row. */
export function taskPostKind(content) {
  const text = String(content ?? "");
  if (text.startsWith(TASK_POST_PREFIX)) return "routine";
  return text.startsWith(JOB_POST_PREFIX) ? "job" : null;
}

/** The head's task name and time; both null when it cannot be parsed, with the raw text kept. */
export function parseTaskPostHead(content) {
  const raw = String(content ?? "");
  const match = HEAD.exec(raw);
  return { raw, name: match ? match[1] : null, time: match?.[2] ?? null };
}
