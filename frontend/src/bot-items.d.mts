import type { Bot, BotFocus, BotTemplate, BotTool, CatalogModel, ModelCatalog } from "./api";
export function botSections(bots: Bot[], options?: { showHidden?: boolean }): { top: Bot | null; groups: Array<{ name: string; bots: Bot[] }> };
export * from "./bot-form-items.mjs";
