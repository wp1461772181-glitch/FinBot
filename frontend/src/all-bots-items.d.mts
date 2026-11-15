import type { Bot, ModelCatalog } from "./api";
export function orderAllBots(bots: Bot[] | null | undefined): Bot[];
export type AgoParts = { now: true } | { unit: "minute" | "hour" | "day" | "month" | "year"; value: number };
export function agoParts(iso: string | null | undefined, nowMs: number): AgoParts | null;
export function cardStatus(bot: Bot, lineStatus?: { running?: string[]; unseen?: string[]; waiting?: string[] }): { status: "answering" | "waiting" | "unread" | "idle"; word: "running" | "waiting" | null; count: number };
export function cardModel(bot: Bot, catalog: ModelCatalog | null | undefined): string | null;
