import type { V2EvaluationResponse, V2ForecastJob, V2ForecastRoots, V2ModelStatus, V2MonitorStatus, V2Probabilities, V2SourceRef, V2Timeline, V2VersionDetail } from "../types";
import { ApiError, agentPath, newIdempotencyKey, ownerHeaders, requestJson } from "./base";

export async function getV2Job(jobId: string, signal?: AbortSignal): Promise<V2ForecastJob> {
  return requestJson<V2ForecastJob>(`/api/v2/jobs/${encodeURIComponent(jobId)}`, { signal });
}

export async function getV2Timeline(rootId: string, signal?: AbortSignal): Promise<V2Timeline> {
  return requestJson<V2Timeline>(`/api/v2/forecast-roots/${encodeURIComponent(rootId)}/timeline`, { signal });
}

export async function getV2ForecastRoots(symbol: string, signal?: AbortSignal): Promise<V2ForecastRoots> {
  return requestJson<V2ForecastRoots>(`/api/v2/stocks/${encodeURIComponent(symbol)}/forecast-roots`, { signal });
}

export async function getV2MonitorStatus(signal?: AbortSignal): Promise<V2MonitorStatus> {
  return requestJson<V2MonitorStatus>("/api/v2/monitor/status", { signal });
}

export async function getV2Evaluations(symbol?: string, signal?: AbortSignal): Promise<V2EvaluationResponse> {
  const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
  return requestJson<V2EvaluationResponse>(`/api/v2/evaluations${query}`, { signal });
}

export type V2Decider = {
  provider: string | null;
  actual_model: string | null;
  question_version: string | null;
  time_mode: string | null;
  decision_mode: string | null;
  binding: { source: "role" | "server_default" | "role_model_missing"; role_model: string | null } | null;
  calibration_status: string | null;
};
export type V2ForecastListRow = {
  id: string;
  symbol: string;
  decision_at: string;
  target_end_date: string | null;
  model_status: V2ModelStatus;
  latest_version_id: string;
  latest_version_no: number;
  expired: boolean | null;
  decider: V2Decider;
  probabilities: V2Probabilities | null;
  evaluation: { status: string; actual_label: "bearish" | "neutral" | "bullish" | null; result_version: number } | null;
};
export type V2JobAlert = { symbol: string; job_id: string; status: string; error_type: string | null; created_at: string };
export type V2ForecastList = { forecasts: V2ForecastListRow[]; limit: number; pending_job_count: number; job_alerts: V2JobAlert[] };

/** Every company's forecasts in one call (public, no personal data); the browser merges holdings and the queue. */
export async function getV2Forecasts(options: { symbols?: string[]; state?: "open" | "matured" | "all"; limit?: number } = {}, signal?: AbortSignal): Promise<V2ForecastList> {
  const query = new URLSearchParams();
  if (options.symbols?.length) query.set("symbols", options.symbols.join(","));
  if (options.state) query.set("state", options.state);
  if (options.limit) query.set("limit", String(options.limit));
  const text = query.toString();
  return requestJson<V2ForecastList>(`/api/v2/forecasts${text ? `?${text}` : ""}`, { signal });
}

export type EarningsJudgment = {
  id: string;
  symbol: string;
  accession: string;
  source_url: string | null;
  accepted_at: string;
  held: boolean;
  followup_status: string;
  delivered: boolean;
  direction: "up" | "down" | "unclear" | null;
  confidence: "high" | "medium" | "low" | null;
  /** A fraction: 0.126 is +12.6%. */
  after_hours: number | null;
  reasons: Array<{ text: string; quote: string }>;
  counter_argument: string | null;
  validated: boolean;
  model: string | null;
  model_source: "followup" | "first_stage" | null;
  reader_version: string | null;
  outcome: { status: "pending" | "matched" | "mismatched" | "no_marked_move" | "not_applicable"; reaction: number | null; sigma: number | null };
  filing_source_id: string | null;
  promotion: { available: boolean; reason: "first_session_open" | "filing_not_in_library" | null };
};

async function ownerGet<T>(path: string, failure: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(agentPath(path), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(failure, response.status);
  return await response.json() as T;
}

/** The owner's earnings judgments, sent or skipped.  A guest gets 401/403, which callers treat as "no such lane". */
export async function getEarningsJudgments(options: { symbol?: string; limit?: number } = {}, signal?: AbortSignal): Promise<EarningsJudgment[]> {
  const query = new URLSearchParams();
  if (options.symbol) query.set("symbol", options.symbol);
  if (options.limit) query.set("limit", String(options.limit));
  const text = query.toString();
  const data = await ownerGet<{ judgments?: EarningsJudgment[] }>(`earnings-judgments${text ? `?${text}` : ""}`, "财报判断暂时无法读取。", signal);
  return Array.isArray(data.judgments) ? data.judgments : [];
}

export async function getEarningsJudgment(id: string, signal?: AbortSignal): Promise<EarningsJudgment> {
  const data = await ownerGet<{ judgment: EarningsJudgment }>(`earnings-judgments/${encodeURIComponent(id)}`, "财报判断暂时无法读取。", signal);
  return data.judgment;
}

export async function getV2ForecastVersion(versionId: string, signal?: AbortSignal): Promise<V2VersionDetail> {
  return requestJson<V2VersionDetail>(`/api/v2/forecast-versions/${encodeURIComponent(versionId)}`, { signal });
}

export type V2RevisionCandidate = {
  source_type: "official_filing" | "uploaded_media";
  source_id: string;
  title: string;
  kind: string;
  published_at: string;
  observed_at: string;
  category: "new" | "backfilled" | "preexisting" | "updated" | "reanalyzed";
  badge: string | null;
};

export type V2RevisionCandidates = {
  version_id: string;
  version_no: number;
  symbol: string;
  decision_at: string;
  window_start: string;
  window_end: string;
  target_end_date: string | null;
  expired: boolean;
  candidates: V2RevisionCandidate[];
  excluded: Array<{
    source_type: "official_filing" | "uploaded_media";
    source_id: string;
    title: string;
    kind: string;
    published_at: string;
    reason: string;
    reason_text: string | null;
  }>;
};

export async function getV2RevisionCandidates(versionId: string, signal?: AbortSignal): Promise<V2RevisionCandidates> {
  return requestJson<V2RevisionCandidates>(`/api/v2/forecast-versions/${encodeURIComponent(versionId)}/revision-candidates`, { signal });
}

export async function createV2ForecastJob(symbol: string, sourceRefs: V2SourceRef[] = []): Promise<V2ForecastJob> {
  return requestJson<V2ForecastJob>("/api/v2/forecast-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": newIdempotencyKey() },
    body: JSON.stringify({ symbol, kind: "new", source_refs: sourceRefs }),
  });
}

export async function createV2HistoricalReplayJob(symbol: string, decisionDate: string): Promise<V2ForecastJob> {
  return requestJson<V2ForecastJob>("/api/v2/historical-replays", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": newIdempotencyKey() },
    body: JSON.stringify({ symbol, decision_date: decisionDate }),
  });
}

export async function createV2ManualRevisionJob(versionId: string, sourceRefs: V2SourceRef[]): Promise<V2ForecastJob> {
  return requestJson<V2ForecastJob>(`/api/v2/forecast-versions/${encodeURIComponent(versionId)}/revision-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": newIdempotencyKey() },
    body: JSON.stringify({ source_refs: sourceRefs }),
  });
}

