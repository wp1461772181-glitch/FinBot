import type { Skill } from "./api";
export const MAX_SLASH_MATCHES: number;
export function skillFromHash(hash: string): string | null;
export function skillGroups(skills: Skill[]): { drafts: Skill[]; builtin: Skill[]; mine: Skill[] };
export function slashMatches(skills: Skill[], text: string, usualIds: string[] | null | undefined): Skill[];
export function usableSkills(skills: Skill[]): Skill[];
export { toggleUsual } from "./bot-form-items.mjs";
