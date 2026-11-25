import { ApiError, agentPath, ownerHeaders } from "./base";
import { exportFilename, viewWriteError } from "../memory-overview.mjs";
import type { OwnerViewVersion } from "./owner-views";

/** The counts of the overview head, all computed by the server from the rows. */
export type MemoryCounts = { said: number; typed: number; inferred: number; guesses_confirmed: number; guesses_waiting: number; archived: number; views_current: number; views_companies: number; watch: number };
/** One company's views: the current one (or null) and every version, each with its latest 回头看 (the shape `GET /views/{symbol}/history` returns). */
export type OverviewCompany = { symbol: string; name: string; current: OwnerViewVersion | null; versions: OwnerViewVersion[] };
/** A portfolio plan with at least one price or some text; prices are the server's own text (or null). */
export type WatchPlan = { symbol: string; plan_text: string; add_price: string | number | null; stop_price: string | number | null; target_price: string | number | null; updated_at: string | null };
export type WatchRoutine = { id: string; name: string; enabled: boolean; scope: "research_queue" | "symbols" | string; symbols: string[]; filings: boolean; news: boolean; price_lines: unknown; next_run_at: string | null; bot_id: string | null };
/** `research_queue` is null when the queue was never saved. */
export type MemoryWatch = { plans: WatchPlan[]; alert_routines: WatchRoutine[]; research_queue: string[] | null; default_rules_note: string };
export type MemoryJob = { job: "monthly_review" | "quarterly_settle" | string; title: string; next_due: string | null; last_run_at: string | null; last_outcome: "done" | "skipped" | "failed" | string | null; last_reason: string | null; messages_until_early?: number };
/** The parts are each null when they could not be built; `errors` names those that failed (counts, views, watch, jobs, seen_block).  `seen_block` is also null when the owner has no profile. */
export type MemoryOverview = { counts: MemoryCounts | null; views: OverviewCompany[] | null; watch: MemoryWatch | null; jobs: MemoryJob[] | null; seen_block: string | null; errors: string[] };

/** The whole 它眼中的你 page's data in one read.  Owner only: a guest gets 403. */
export async function getMemoryOverview(signal?: AbortSignal): Promise<MemoryOverview> {
  const response = await fetch(agentPath("memory/overview"), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能查看它眼中的你。" : "它眼中的你暂时无法读取。", response.status);
  const data = await response.json().catch(() => null) as Partial<MemoryOverview> | null;
  if (!data || typeof data !== "object") throw new ApiError("它眼中的你暂时无法读取。", response.status);
  return {
    counts: data.counts ?? null, views: Array.isArray(data.views) ? data.views : null, watch: data.watch ?? null, jobs: Array.isArray(data.jobs) ? data.jobs : null,
    seen_block: typeof data.seen_block === "string" ? data.seen_block : null, errors: Array.isArray(data.errors) ? data.errors.map(String) : [],
  };
}

/** The owner downloads everything as one file: JSON (complete) or Markdown (to read).  The file is made in the browser from the response, with the session header. */
export async function downloadMemoryExport(format: "json" | "md", signal?: AbortSignal): Promise<void> {
  const response = await fetch(agentPath(`memory/export?format=${format}`), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能导出。" : "导出失败，请重试。", response.status);
  const blob = new Blob([await response.blob()], { type: format === "md" ? "text/markdown;charset=utf-8" : "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = exportFilename(format); document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
}

async function viewWrite(path: string, body: unknown): Promise<unknown> {
  const response = await fetch(agentPath(path), { method: "POST", cache: "no-store", headers: ownerHeaders(body !== undefined), ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new ApiError(viewWriteError(response.status, payload?.detail), response.status);
  }
  return await response.json().catch(() => null);
}
/** The owner writes (or changes) his view of a company on the page: a new version, his typed words being their own quote.  A refusal carries the Chinese reason. */
export async function writeOwnerView(symbol: string, text: string): Promise<OwnerViewVersion | null> {
  const data = await viewWrite(`views/${encodeURIComponent(symbol)}`, { text }) as { view?: OwnerViewVersion } | null;
  return data?.view ?? null;
}
/** The owner withdraws his current view of a company (the history stays). */
export async function dropOwnerView(symbol: string): Promise<void> {
  await viewWrite(`views/${encodeURIComponent(symbol)}/drop`, undefined);
}
