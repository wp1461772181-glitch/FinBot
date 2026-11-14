import type { EvidenceRevision, EvidenceRevisionInventory, EvidenceRevisionRequest, UploadedEvidence, UploadedEvidenceInventory } from "../types";
import { chatCredential, requestJson } from "./base";

export async function getUploadedEvidence(symbol: string, signal?: AbortSignal): Promise<UploadedEvidenceInventory> {
  return requestJson<UploadedEvidenceInventory>(`/api/uploaded-evidence/${encodeURIComponent(symbol)}`, { signal });
}

export async function uploadEvidence(
  symbol: string,
  input: {
    file: File;
    title: string;
    sourceUrl: string;
    publishedAt: string;
    credibilityStars: number;
    credibilityReason: string;
    impactSeverity: "low" | "medium" | "high";
  },
): Promise<UploadedEvidence> {
  const form = new FormData();
  form.set("file", input.file);
  form.set("title", input.title);
  form.set("source_url", input.sourceUrl);
  form.set("published_at", input.publishedAt);
  form.set("credibility_stars", String(input.credibilityStars));
  form.set("credibility_reason", input.credibilityReason);
  form.set("impact_severity", input.impactSeverity);
  return requestJson<UploadedEvidence>(`/api/uploaded-evidence/${encodeURIComponent(symbol)}`, { method: "POST", headers: { "X-Chat-Session": chatCredential() }, body: form });
}

export async function getEvidenceRevisions(symbol: string, signal?: AbortSignal): Promise<EvidenceRevisionInventory> {
  return requestJson<EvidenceRevisionInventory>(`/api/evidence-revisions/${encodeURIComponent(symbol)}`, { signal });
}

export async function createEvidenceRevision(symbol: string, input: EvidenceRevisionRequest): Promise<EvidenceRevision> {
  return requestJson<EvidenceRevision>(`/api/evidence-revisions/${encodeURIComponent(symbol)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

