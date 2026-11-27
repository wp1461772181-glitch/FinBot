import { requestJson } from "./base";
import { answersQuery, feedbackBody, pagedQuery, usageQuery, type AnswerFilters, type Verdict } from "../backstage-view.mjs";

// 后台: the owner's look behind the answers.  Every call here is a GET except sendFeedback (「有用／没用」 on a duty or brief message); the server
// answers 403 to anyone who is not the owner.

export type Tokens = { input?: number; output?: number; cache_read?: number; cache_write?: number; total?: number };
export type AnswerItem = { message_id: string; conversation_id: string; bot_id: string | null; bot_name: string | null; created_at: string; question: string; answer: string;
  engine: "v1" | "v2" | null; status: string; tier: "low" | "mid" | "high" | null; models: string[]; total_ms: number | null; model_calls: number; tokens: Tokens; cost_usd: number | null;
  tool_count: number; write_outcomes: string[]; write_outcome: string | null; reconcile?: "flagged" | "clean" | "error" | null };
export type AnswersPage = { items: AnswerItem[]; next_before: string | null; slow_threshold_ms: number | null; slow_rule: string | null };

export type ModelCall = { tier: string | null; model: string; catalog_name: string | null; purpose: string; ms: number | null; tokens: Tokens; attempt: number; ok: boolean; error: string | null; cost_usd: number | null; priced: boolean; at: string };
export type ToolCall = { call_id: string; name: string; arguments: Record<string, unknown>; status: string; result: { ok: boolean; error_code: string | null; count: number | null; row_titles: string[] } | null };
export type Citation = { ordinal: number; title: string; url: string | null; source_type: string };
/** The figure check run after a kernel answer (5d-1); null when the answer was not checked. */
export type Reconciliation = { state: "flagged" | "clean" | "error"; figures: number | null; flagged: Array<{ line: string; values: string[] }>; error: string | null };
export type AnswerDetail = {
  message_id: string; conversation_id: string; turn_id: string; bot_id: string | null; bot_name: string | null; created_at: string; engine: "v1" | "v2" | null; partial: boolean; status: string; tier: string | null; total_ms: number | null;
  question: string; model_calls: ModelCall[]; model_calls_source: string; narration: string[]; checklist: Array<{ item: string; state: string }>; tool_calls: ToolCall[]; citations: Citation[];
  writes: Array<{ operation: string; tier: number; outcome: string }>; write_outcome: string | null;
  card: { request_id: string; reason: string; title: string; targets: unknown[]; question: string | null; choices: Array<{ label: string; kind: string }>;
    consent: { status: string; expired: boolean; decided_at: string | null; operations: unknown[]; result: unknown } | null } | null;
  answer: string; backup_model: { from: string | null; to: string | null; reason: string | null } | null; latest_known?: string[]; langfuse_url: string | null;
  reconciliation?: Reconciliation | null;
};

export type UsageGroup = { key: string; label: string; calls: number; failed_calls: number; tokens: Tokens; ms_p50: number | null; cost_usd: number | null; unpriced_calls: number; missing_prices: string[] };
export type Usage = { from: string; to: string; group: string; timezone: string; timezone_note: string; totals: Omit<UsageGroup, "key" | "label">; groups: UsageGroup[] };

export type OperationItem = { id: string; conversation_id: string; bot_id: string | null; bot_name: string | null; created_at: string; expires_at: string; title: string; targets: unknown[]; operations: unknown[];
  status: string; expired: boolean; decided_at: string | null; result: unknown };
export type DeliveryItem = { id: string; group_id: string | null; bot_id: string | null; source: string; channel: string; status: string; failure: string | null; created_at: string; sent_at: string | null; acked_at: string | null; text: string;
  feedback?: Verdict | null };
export type Paged<T> = { items: T[]; next_before: string | null };
export type DutyItem = { id: number; created_at: string; alert_id: number; symbol: string | null; kind: string | null; what: string; mode: "off" | "shadow" | "on"; outcome: string;
  decision: "tell_now" | "digest" | "record" | "ignore" | null; reason: string | null; message: string | null; delivery: string | null; turn_id: string | null; message_id: string | null; ms: number; model_calls: number };
export type DutyPage = Paged<DutyItem> & { mode: "off" | "shadow" | "on" };

const get = <T,>(path: string, signal?: AbortSignal) => requestJson<T>(`/api/backstage/${path}`, { signal });

export const listAnswers = (filters: Partial<AnswerFilters>, signal?: AbortSignal) => get<AnswersPage>(`answers${answersQuery(filters)}`, signal);
export const readAnswer = (id: string, signal?: AbortSignal) => get<AnswerDetail>(`answers/${encodeURIComponent(id)}`, signal);
export const readUsage = (options: { from?: string; to?: string; group?: string }, signal?: AbortSignal) => get<Usage>(`usage${usageQuery(options)}`, signal);
export const listOperations = (before: string | null, signal?: AbortSignal) => get<Paged<OperationItem>>(`operations${pagedQuery(before)}`, signal);
export const listDeliveries = (before: string | null, signal?: AbortSignal) => get<Paged<DeliveryItem>>(`deliveries${pagedQuery(before)}`, signal);
export const listDuty = (before: string | null, signal?: AbortSignal) => get<DutyPage>(`duty${pagedQuery(before)}`, signal);
export const sendFeedback = (group: string, verdict: Verdict) => requestJson<{ verdict: Verdict }>("/api/backstage/feedback", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(feedbackBody(group, verdict)) });
