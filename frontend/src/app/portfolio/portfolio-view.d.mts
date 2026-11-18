import type { PortfolioPlanForm } from "../../portfolio-items.mjs";
export type PnlView = { direction: "up" | "down" | "flat" | "none"; text: string; signed: boolean };
export function pnlView(value: unknown, options?: { percent?: boolean }): PnlView;
export type LedgerCells = { label: string; quantity: string | null; price: string | null; fee: string | null };
export function ledgerCells(tx: { kind: string; quantity?: string | null; price?: string | null; fee?: string | null; amount?: string | null; ratio?: string | null }): LedgerCells;
export function recordsOf<T extends { symbol: string }>(transactions: T[] | null | undefined, symbol: string): T[];
export function planDraft(plan: Parameters<typeof import("../../portfolio-items.mjs").planForm>[0], draft: PortfolioPlanForm | undefined): { form: PortfolioPlanForm; changed: boolean };
