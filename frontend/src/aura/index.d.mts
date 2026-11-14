import type { AuraFn } from "./shared.mjs";
export const AURAS: Record<string, AuraFn>;
/** The aura of a persona's variant name (an unknown name is the generalist's dots). */
export function auraFor(variant: string | null | undefined): AuraFn;
export { PHASES, TONES, endLength } from "./shared.mjs";
