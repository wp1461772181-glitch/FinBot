import type { Bot, BotFields, BotTool } from "./api";
import type { BloubLook } from "./bloub-look.mjs";

export type SectionId = "profile" | "focus" | "look" | "model" | "tools" | "skills" | "routines" | "notify" | "danger";
export declare const SECTIONS: ReadonlyArray<{ id: SectionId; label: string; save: "bar" | "live" | "now" }>;
export declare const DEFAULT_SECTION: SectionId;
export declare const SECTION_OF_FIELD: Record<string, SectionId>;
export declare function sectionFromSearch(search: string | null | undefined): SectionId;

export type BotDraft = {
  name: string; title: string; description: string; focus: Bot["focus"]; tool_scope: string[] | null; model: string | null; reasoning_effort: string | null;
  template: string; avatar: string; look: BloubLook | null; seed: string; group: string; pinned: boolean; hidden: boolean; daily_notify_cap: number;
};
export declare function draftOf(bot: Bot): BotDraft;
export declare function fieldsToSave(draft: BotDraft, bot?: Bot | null): BotFields;
export declare function changedFields(draft: BotDraft, bot: Bot): string[];
export declare function hasChanges(draft: BotDraft, bot: Bot): boolean;
export declare function sectionsChanged(draft: BotDraft, bot: Bot): Set<SectionId>;
export declare function validate(draft: BotDraft): { name?: string };

export declare function focusSymbols(draft: BotDraft): string[];
export declare function withFocusSymbols(draft: BotDraft, symbols: string[]): BotDraft;
export declare function withFocusTheme(draft: BotDraft, theme: string): BotDraft;

export declare const TOOL_GROUPS: ReadonlyArray<{ id: "read" | "web" | "write" | "other"; label: string }>;
export declare function toolGroup(tool: BotTool): "read" | "web" | "write" | "other";
export declare function groupTools(tools: BotTool[]): Array<{ id: "read" | "web" | "write" | "other"; label: string; tools: BotTool[] }>;
export declare function scopeSummary(scope: string[] | null | undefined, total: number): { all: boolean; count: number; total: number };

export declare const TELEGRAM_STEPS: readonly string[];
export declare function telegramStep(state: { bound?: boolean; has_token?: boolean } | null | undefined, bind: unknown): 0 | 1 | 2 | 3;
