import type { AgentCitation, KnowledgeCitationDetail } from "./api";

export const LINKED_TYPES: string[];
export function sourceTypeLabel(type: unknown): string;
export function isDerived(citation: AgentCitation | null | undefined, detail?: KnowledgeCitationDetail | null): boolean;
export function derivedDetail(detail: KnowledgeCitationDetail | null | undefined): string;
export function formatStamp(value: unknown, zone?: string): string;
export function sourceDates(citation: AgentCitation | null | undefined, zone?: string): { published: string | null; publishedUnknown: boolean; observed: string | null; observedUnknown: boolean; web: boolean };
export function originalHref(citation: AgentCitation | null | undefined, detail?: KnowledgeCitationDetail | null): string | null;
export function excerptSource(citation: AgentCitation | null | undefined): "unavailable" | "chunk" | "quote" | "none";
