export type SupportedSymbol = string;
export type WorkspaceSection = "overview" | "forecast" | "evidence" | "materials" | "revisions" | "evaluation" | "replay" | "agent" | "bot" | "admin" | "routines" | "portfolio" | "news" | "skills" | "memory" | "me" | "knowledge";
export type ResearchSection = Exclude<WorkspaceSection, "agent" | "bot" | "admin" | "routines" | "portfolio" | "news" | "skills" | "memory" | "me" | "knowledge">;
export type NavGroup = "chat" | "routines" | "portfolio" | "news" | "company" | "forecast" | "library" | "skills" | "memory" | "settings";
export function navGroup(section: WorkspaceSection): NavGroup;
export function isResearchSection(section: WorkspaceSection): section is ResearchSection;
export const WORKSPACE_SECTION_TITLE: Record<ResearchSection, string>;
