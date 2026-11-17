import { monitorChip } from "../../../data-display.mjs";
import { monitorDot } from "../../monitor-dot.mjs";

export { monitorDot };

// The monitor page's pure rules (P6.4): what each health state looks like, the moments of the run timeline, and the rows of the per-company table.
// The health itself is the server's (`health` of GET /v2/monitor/status); nothing here decides whether the monitor is well.

/** The four states, in the order the sample pages show them. */
export const MONITOR_HEALTHS = ["healthy", "delayed", "degraded", "not_recorded"];

/**
 * One health state: the badge kind and words of the chip (the same chip as the watchlist, the company page and the forecast home: `monitorChip`), the headline
 * of the health card, and the colour of the sidebar dot (`null` = no dot).  Normal and no-record show nothing beside 研究; a late or failing monitor does.
 */
export function monitorState(health) {
  const chip = monitorChip(health);
  switch (health) {
    case "healthy": return { id: "healthy", ...chip, headline: "最近扫描成功", dot: null };
    case "delayed": return { id: "delayed", ...chip, headline: "运行延迟", dot: monitorDot(health) };
    case "degraded": return { id: "degraded", ...chip, headline: "部分失败或降级", dot: monitorDot(health) };
    default: return { id: "not_recorded", ...chip, headline: "没有运行记录", dot: null };
  }
}

/** The words for a run's own status. */
export const RUN_STATUS_PHRASE = { succeeded: "成功", partial: "部分失败", failed: "失败", running: "进行中" };
/** The words for one company's result. */
export const SYMBOL_STATUS_PHRASE = { succeeded: "成功", incomplete: "未完整扫描", failed: "失败" };
/** The badge kind of a company's result (a failure is a failure; a partial scan is neutral, it did not fail). */
export const SYMBOL_STATUS_KIND = { succeeded: "success", incomplete: "neutral", failed: "failure" };

/**
 * The moments the page can show of the monitor, newest first: the last run, and the last run that fully succeeded when that is another run.  The server
 * keeps those two and no more, so the timeline has one or two items; when they are the same run it is one item that says so.
 */
export function runMoments(status) {
  const run = status?.last_run ?? null;
  if (!run) return [];
  const success = status?.last_success ?? null;
  const same = success !== null && success.id === run.id;
  const moments = [{ id: "last-run", kind: "run", status: run.status, startedAt: run.started_at, completedAt: run.completed_at, nextDueAt: run.next_due_at, alsoLastSuccess: same }];
  if (success && !same) moments.push({ id: "last-success", kind: "success", status: "succeeded", startedAt: null, completedAt: success.completed_at, nextDueAt: null, alsoLastSuccess: true });
  return moments;
}

const SEVERITY = { failed: 0, incomplete: 1, succeeded: 2 };

/**
 * The rows of the per-company table: code, result, a note.  The note is the error the monitor recorded, else what it found (the old counts).  Failures first,
 * then partial scans, then the rest; inside a group the server's order is kept.
 */
export function symbolRows(run) {
  const entries = Object.entries(run?.per_symbol_results ?? {});
  return entries
    .map(([ticker, result], index) => ({
      ticker, index, status: result.status,
      error: result.error ?? null,
      discovered: result.discovered_count ?? 0, created: result.created_count ?? 0, queued: result.queued_count ?? 0,
    }))
    .sort((a, b) => (SEVERITY[a.status] ?? 3) - (SEVERITY[b.status] ?? 3) || a.index - b.index)
    .map(({ index, ...row }) => row);
}

/** The late-after threshold in whole hours, as the old page wrote it. */
export function staleHours(staleAfterSeconds) {
  return Math.round((Number(staleAfterSeconds) || 0) / 3600);
}
