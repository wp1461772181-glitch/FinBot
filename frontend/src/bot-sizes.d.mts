export declare const BOT_AVATAR_SIZE: { message: number; sidebar: number; title: number; emoji: number; mobileFloor: number; hero: number; createHero: number; login: number };
export type Tier = "XS" | "S" | "M" | "L";
export declare const BOT_TIERS: Record<Tier, { min: number; max: number }>;
export declare function tierOf(size: number): Tier;
export declare const FULL_TIERS: Tier[];
