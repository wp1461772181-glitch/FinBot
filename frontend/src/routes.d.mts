export type CompanyTab = "overview" | "forecasts" | "materials";
export type RoutineTab = "confirm" | "tasks" | "runs";
export type SourceType = "official_filing" | "uploaded_media";
export type SettingsSection = "models" | "notifications" | "appearance" | "data" | "account";
export type AssistantSection = "bots" | "skills" | "memory" | "news" | "knowledge";
/** The old section names the shell's highlight and tabs are written against. */
export type NavSection = "agent" | "bot" | "overview" | "forecast" | "revisions" | "evaluation" | "replay" | "evidence" | "materials" | "routines" | "portfolio" | "news" | "skills" | "memory" | "me" | "knowledge" | "admin";
export type MaterialFocusParams = { symbol: string; source_type: SourceType; source_id: string | null; analysis_id: string | null };

export const COMPANY_TABS: readonly CompanyTab[];
export const ROUTINE_TABS: readonly RoutineTab[];
export const SETTINGS_SECTIONS: readonly SettingsSection[];
export const ASSISTANT_SECTIONS: readonly AssistantSection[];
export const SOURCE_TYPES: readonly SourceType[];
export const PATTERNS: Record<"login" | "chat" | "chatBot" | "chatBotSettings" | "chatConversation" | "chatHistory" | "research" | "company" | "companyLatest" | "forecasts" | "forecast" | "judgment" | "evidenceIndex" | "evidence" | "evidenceSource" | "materials" | "scores" | "replay" | "monitor" | "portfolio" | "routines" | "assistantBots" | "assistantSkills" | "assistantSkill" | "assistantMemory" | "assistantNews" | "assistantKnowledge" | "settings" | "devKit" | "devKitProbe" | "devKitStates" | "devKitBots", string>;

export const paths: {
  login(): string;
  chat(botId?: string | null): string;
  chatSettings(botId: string): string;
  chatConversation(conversationId: string): string;
  chatHistory(): string;
  research(): string;
  company(symbol: string, tab?: CompanyTab): string;
  companyLatest(symbol: string, options?: { section?: string }): string;
  forecasts(options?: { symbol?: string | null }): string;
  forecast(rootId: string, options?: { version?: string | null; revise?: string | null; section?: string | null }): string;
  judgment(eventId: string): string;
  evidence(versionId: string, sourceType?: string | null, sourceId?: string | null): string;
  evidenceIndex(options?: { symbol?: string | null; upload?: boolean }): string;
  materials(options?: { symbol?: string | null; focus?: string | null; type?: string | null; analysis?: string | null }): string;
  scores(): string;
  replay(): string;
  monitor(): string;
  portfolio(): string;
  routines(options?: { tab?: string | null }): string;
  assistant(section?: AssistantSection): string;
  skill(skillId: string): string;
  settings(section?: SettingsSection): string;
  devKit(options?: { probe?: boolean; states?: boolean; bots?: boolean }): string;
};

export function symbolParam(value: unknown): string;
export function hashHref(path: string): string;
export function splitPath(path: string): { pathname: string; params: URLSearchParams };
export function companyTab(params: URLSearchParams): CompanyTab;
export function routinesTab(params: URLSearchParams): RoutineTab | null;
export function symbolFromParams(params: URLSearchParams): string | null;
export function materialFocusFromParams(params: URLSearchParams): MaterialFocusParams | null;
export function isRecordId(value: unknown): boolean;
export function sourceTypeParam(value: unknown): SourceType | null;
export function sectionOfPath(path: string): NavSection;
export function pathForSection(section: string, symbol?: string | null): string;
