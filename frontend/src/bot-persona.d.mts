import type { BloubLook } from "./bloub-look.mjs";
export type Archetype = "lead" | "tracker" | "sentinel" | "reader" | "generalist";
export type Easing = "smooth" | "spring" | "step";
export type RestGaze = "follow" | "ahead-right" | "scan" | "down" | "front";
export type PersonaSource = "preset" | "override" | "derived";
export type VolatilityBand = "fast" | "standard" | "calm";
export interface Persona { archetype: Archetype; tempo: number; easing: Easing; restGaze: RestGaze; auraVariant: string; source: PersonaSource }
export interface PersonaOverrides { archetype?: Archetype; tempo?: number; easing?: Easing }
/** The slice of a bot record the personality reads. */
export interface PersonaBot {
  id?: string | null; name?: string | null; template?: string | null; is_default?: boolean;
  default_company?: { symbol?: string | null } | null; focus?: { companies?: Array<{ symbol?: string | null }> } | null;
}
export interface PersonaPreset { id: string; name: string; archetype: Archetype; tempo: number; easing: Easing; restGaze: RestGaze; auraVariant: string; look: BloubLook }
export interface StorageLike { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void }
export declare const ARCHETYPES: Archetype[];
export declare const EASINGS: Easing[];
export declare const REST_GAZES: RestGaze[];
export declare const AURA_VARIANTS: Record<Archetype, string[]>;
export declare const TEMPO_MIN: number;
export declare const TEMPO_MAX: number;
export declare const VOL_HIGH: number;
export declare const VOL_LOW: number;
export declare const VOL_WINDOW: number;
export declare const PERSONA_PRESETS: PersonaPreset[];
export declare function presetFor(bot: { id?: string | null; name?: string | null } | null | undefined): PersonaPreset | null;
export declare function presetLook(bot: { id?: string | null; name?: string | null } | null | undefined): BloubLook | null;
export declare function trackedSymbol(bot: PersonaBot | null | undefined): string | null;
export declare function archetypeOf(bot: PersonaBot | null | undefined): Archetype;
export declare function volatilityBand(volatility: unknown): VolatilityBand | null;
export declare function cleanOverrides(raw: unknown): PersonaOverrides;
export declare function derivePersona(bot: PersonaBot | null | undefined, options?: { volatility?: number | null; overrides?: unknown }): Persona;
export declare function readOverrides(storage: StorageLike | null | undefined, botId: string | null | undefined): PersonaOverrides;
export declare function writeOverrides(storage: StorageLike | null | undefined, botId: string | null | undefined, overrides: PersonaOverrides): PersonaOverrides;
export declare function clearOverrides(storage: StorageLike | null | undefined, botId: string | null | undefined): PersonaOverrides;
export declare function annualizedVolatility(closes: unknown): number | null;
export declare function readVolatility(storage: StorageLike | null | undefined, botId: string | null | undefined, symbol: string | null | undefined): number | null;
export declare function writeVolatility(storage: StorageLike | null | undefined, botId: string | null | undefined, symbol: string | null | undefined, value: number): boolean;
