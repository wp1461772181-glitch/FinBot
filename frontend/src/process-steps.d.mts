import type { FlowNode, FlowStatus } from "./turn-flow.mjs";

export type StepChip = { id: string; kind: string; label: string; suffix: string; state: FlowStatus; count: number | null; outcome: "count" | "none" | "failed" | ""; reason: string; reasonKnown: boolean };
export type BarModel = { kind: "running" | "summary" | "time" | "none"; nodes: FlowNode[]; chips: StepChip[]; seconds: string; steps: number; activeLabel: string };
export type LegacyToolChip = { id: string; label: string; state: string; status: string; summary: string };
export function stepChips(nodes: FlowNode[]): StepChip[];
export function barModel(input: { trace?: unknown; thinkingMs?: number; startedAt?: number; running: boolean; now?: number }): BarModel;
export function toolResultSummary(value: unknown): string;
export function legacyToolChips(toolTrace: unknown): LegacyToolChip[];
