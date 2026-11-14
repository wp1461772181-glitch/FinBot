import type { LocalizationResult, MaterialAnalysisHistory, MaterialAnalysisJob, MaterialAnalysisVersion, MaterialLibraryResponse, MaterialOriginal, MaterialSourceType } from "../types";
import { newIdempotencyKey, requestJson } from "./base";
import type { AgentChatProvider } from "./conversations";

export async function getMaterialLibrary(
  symbol: string,
  options: { sourceType?: MaterialSourceType | "all"; analysisStatus?: string; reviewStatus?: string; order?: "published" | "recent"; offset?: number; limit?: number; signal?: AbortSignal } = {},
): Promise<MaterialLibraryResponse> {
  // An empty symbol is 全部股票: the library lists every stock's materials.
  const params = new URLSearchParams({ limit: String(options.limit ?? 10), offset: String(options.offset ?? 0) });
  if (symbol) params.set("symbol", symbol);
  if (options.order && options.order !== "published") params.set("order", options.order);
  if (options.sourceType && options.sourceType !== "all") params.set("source_type", options.sourceType);
  if (options.analysisStatus && options.analysisStatus !== "all") params.set("analysis_status", options.analysisStatus);
  if (options.reviewStatus && options.reviewStatus !== "all") params.set("review_status", options.reviewStatus);
  return requestJson<MaterialLibraryResponse>(`/api/v3/materials?${params}`, { signal: options.signal });
}

/** A server catalog entry for one analysis (UX batch 3); the provider form is kept for older callers. */
export type MaterialAnalysisModelOverride = { catalog_model: string } | {
  provider: AgentChatProvider;
  base_url?: string;
  model: string;
  api_key: string;
};
export type MaterialAnalysisSettings = {
  source: "environment" | "settings";
  provider: AgentChatProvider;
  base_url: string | null;
  model: string;
  has_api_key: boolean;
  api_key_last4: string | null;
};

export async function createMaterialAnalysisJob(
  sourceType: MaterialSourceType,
  sourceId: string,
  force = false,
  model?: MaterialAnalysisModelOverride,
): Promise<MaterialAnalysisJob> {
  const idempotencyKey = newIdempotencyKey();
  const body = {
    idempotency_key: idempotencyKey,
    force,
    ...(model ? "catalog_model" in model ? { catalog_model: model.catalog_model } : { provider: model.provider, base_url: model.base_url, model: model.model, api_key: model.api_key } : {}),
  };
  return requestJson<MaterialAnalysisJob>(`/api/v3/materials/${sourceType}/${encodeURIComponent(sourceId)}/analysis-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(body),
  });
}

export async function getMaterialAnalysisSettings(signal?: AbortSignal): Promise<MaterialAnalysisSettings> {
  return requestJson<MaterialAnalysisSettings>("/api/v3/materials/analysis-settings", { signal });
}

export async function saveMaterialAnalysisSettings(
  settings: { provider: AgentChatProvider; base_url?: string; model: string; api_key?: string } | { catalog_model: string },
  signal?: AbortSignal,
): Promise<MaterialAnalysisSettings> {
  return requestJson<MaterialAnalysisSettings>("/api/v3/materials/analysis-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
    signal,
  });
}

export async function resetMaterialAnalysisSettings(signal?: AbortSignal): Promise<MaterialAnalysisSettings> {
  return requestJson<MaterialAnalysisSettings>("/api/v3/materials/analysis-settings", { method: "DELETE", signal });
}

export async function getMaterialAnalysisJob(jobId: string, signal?: AbortSignal): Promise<MaterialAnalysisJob> {
  return requestJson<MaterialAnalysisJob>(`/api/v3/material-analysis-jobs/${encodeURIComponent(jobId)}`, { signal });
}

export async function getMaterialAnalysisHistory(
  sourceType: MaterialSourceType,
  sourceId: string,
  signal?: AbortSignal,
): Promise<MaterialAnalysisHistory> {
  return requestJson<MaterialAnalysisHistory>(`/api/v3/materials/${sourceType}/${encodeURIComponent(sourceId)}/analyses`, { signal });
}

export async function getMaterialAnalysis(analysisId: string, signal?: AbortSignal): Promise<MaterialAnalysisVersion> {
  return requestJson<MaterialAnalysisVersion>(`/api/v3/material-analyses/${encodeURIComponent(analysisId)}`, { signal });
}

export async function localizeMaterialAnalysis(analysisId: string, signal?: AbortSignal): Promise<LocalizationResult> {
  return requestJson<LocalizationResult>(`/api/v3/material-analyses/${encodeURIComponent(analysisId)}/localization`, { method: "POST", signal });
}

export async function localizeForecastBrief(versionId: string, signal?: AbortSignal): Promise<LocalizationResult> {
  return requestJson<LocalizationResult>(`/api/v2/forecast-versions/${encodeURIComponent(versionId)}/brief-localization`, { method: "POST", signal });
}

export async function getMaterialOriginal(
  sourceType: MaterialSourceType,
  sourceId: string,
  signal?: AbortSignal,
): Promise<MaterialOriginal> {
  return requestJson<MaterialOriginal>(`/api/v3/materials/${sourceType}/${encodeURIComponent(sourceId)}/original`, { signal });
}

