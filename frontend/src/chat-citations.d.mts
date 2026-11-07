import type { AgentCitation } from "./api";

export function citationOrdinal(citation: AgentCitation | null | undefined, index: number): number;
export function renderAnswerText(text: unknown, citations: unknown, protocol: string | undefined): string;
export function citationsToShow<T>(protocol: string | undefined, citations: T[] | undefined, nodes: unknown[] | undefined): T[];
export function linkCitationMarkers(text: string | null | undefined, citations: AgentCitation[] | null | undefined): string;
