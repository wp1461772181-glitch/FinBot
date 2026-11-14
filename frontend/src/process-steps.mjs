// What the process bar under an answer says (design 4.2, item 2).  Every word comes from turn-flow.mjs and agent-tool-labels.mjs:
// the chips are the nodes of the trace, their results are what describeOutput already says about a node.  This module only picks
// among those lines; a result the existing functions do not give is not shown, and nothing here decides what a result means.
import { toolLabel } from "./agent-tool-labels.mjs";
import { describeOutput, formatSeconds, nodeTitle, normalizeTrace, stepCount } from "./turn-flow.mjs";

const NOT_STEPS = ["input", "output", "ask"];

/**
 * One chip per step of the trace.  `state` is the node's own status; `count` is the number of hits a finished tool reports,
 * `outcome` is "count" (hits), "none" (it found nothing) or "failed" (with `reason`, a source phrase; `reasonKnown` says it is in
 * the catalogue), and "" when the node says nothing of the kind.
 */
export function stepChips(nodes) {
  const list = Array.isArray(nodes) ? nodes : [];
  return list.filter((node) => node && !NOT_STEPS.includes(node.kind)).map((node) => {
    const title = nodeTitle(node);
    const lines = node.status === "running" ? [] : describeOutput(node);
    const hits = lines.find((line) => line.label === "命中条数");
    const none = lines.find((line) => line.label === "结果" && line.value === "没有匹配记录");
    const failed = lines.find((line) => line.label === "失败原因");
    const count = hits ? Number(hits.value) : null;
    const outcome = failed ? "failed" : hits && Number.isFinite(count) ? "count" : none ? "none" : "";
    return {
      id: node.id, kind: node.kind, label: title.label, suffix: title.suffix, state: node.status,
      count: outcome === "count" ? count : null, outcome,
      reason: failed ? failed.value : "", reasonKnown: Boolean(failed && failed.translate),
    };
  });
}

/**
 * The shape of the bar.  `running`: the chips so far plus the slot (the first cell: dots, a state text, the seconds).  `summary`: a
 * finished turn folded to 「已思考 N 秒 · M 步」 (it opens the panel).  `time`: no trace, only the time (static, as the old panel
 * showed it).  `none`: nothing to say.  `steps` is the number the old header counted.
 */
export function barModel({ trace, thinkingMs, startedAt, running, now }) {
  const nodes = normalizeTrace(trace);
  const elapsed = typeof startedAt === "number" && Number.isFinite(startedAt) && typeof now === "number" ? Math.max(0, now - startedAt) : 0;
  if (running) {
    const active = [...nodes].reverse().find((node) => node.status === "running");
    return { kind: "running", nodes, chips: stepChips(nodes), seconds: formatSeconds(elapsed), steps: stepCount(nodes), activeLabel: active ? nodeTitle(active).label : "" };
  }
  if (nodes.length > 0) return { kind: "summary", nodes, chips: [], seconds: formatSeconds(typeof thinkingMs === "number" ? thinkingMs : 0), steps: stepCount(nodes), activeLabel: "" };
  if (typeof thinkingMs === "number") return { kind: "time", nodes, chips: [], seconds: formatSeconds(thinkingMs), steps: 0, activeLabel: "" };
  return { kind: "none", nodes, chips: [], seconds: "0.0", steps: 0, activeLabel: "" };
}

/** A tool result's short summary, as the old tool badge wrote it (no trace on the message: an answer from before the step graph). */
export function toolResultSummary(value) {
  if (!value || typeof value !== "object") return "";
  if (typeof value.job_status === "string") return `任务 ${value.job_status.slice(0, 32)}`;
  if (Array.isArray(value.data)) return `${value.data.length} 条结果`;
  if (typeof value.error_code === "string") return value.error_code.slice(0, 48);
  return "";
}

const TOOL_STATUS_TEXT = { not_found: "没有匹配记录", failed: "查询失败", cancelled: "已取消", submitted: "已提交" };

/**
 * The old tool badges as chips: name, state phrase and the short summary.  `label` and `status` are source phrases (the caller
 * translates them); `summary` is plain text, as it always was.
 */
export function legacyToolChips(toolTrace) {
  return (Array.isArray(toolTrace) ? toolTrace : []).map((tool, index) => ({
    id: `${tool.name}-${index}`, label: toolLabel(tool.name), state: tool.status,
    status: tool.status === "complete" ? (tool.card ? "执行完成" : "已完成") : TOOL_STATUS_TEXT[tool.status] ?? "执行中",
    summary: toolResultSummary(tool.result),
  }));
}
