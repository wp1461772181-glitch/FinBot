import type { BotTemplate, BotTool, BotFields } from "./api";
export const PREVIEW_BOT_ID: string;
export function createFields(name: string, template: BotTemplate | null | undefined, tools: BotTool[], look: { shape: string; color: string }): BotFields;
export function createName(name: string, template: BotTemplate | null | undefined, tools: BotTool[]): string;
export function previewBot(template: { id: string } | null | undefined, name?: string): { id: string; name: string; template: string; is_default: boolean; default_company: null; focus: { companies: never[]; theme: null } };
