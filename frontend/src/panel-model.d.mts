import type { AgentChatMessage, AgentCitation } from "./api";

export type PanelTab = "sources" | "process" | "workspace" | "profile";
export const PANEL_TABS: PanelTab[];
export const PANEL_MIN: number;
export const PANEL_MAX: number;
export const PANEL_DEFAULT: number;
export const THREAD_MIN: number;
export const PANEL_KEY_STEP: number;
export function availableTabs(options?: { hasWorkspace?: boolean; hasProfile?: boolean }): PanelTab[];
export function initialTab(stored: unknown, available?: PanelTab[]): PanelTab;
export function clampPanelWidth(value: unknown, available?: number): number;
export function storedPanelWidth(raw: unknown, available?: number): number;
export function turnKey(message: AgentChatMessage | null | undefined, index: number): string;
export function hasRoundContent(message: AgentChatMessage | null | undefined): boolean;
export function selectedIndex(messages: AgentChatMessage[], key: string | null | undefined): number;
export function roundQuestion(messages: AgentChatMessage[], index: number, max?: number): string;
export function roundSources(message: AgentChatMessage | null | undefined): AgentCitation[];
