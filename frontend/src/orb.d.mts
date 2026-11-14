export type BotStyle = "kline" | "pure" | "bull" | "square";
export type BotMood = "idle" | "focus" | "bull" | "mono";
export declare const BOT_STYLES: BotStyle[];
export declare const BOT_MOODS: BotMood[];
export declare const DEFAULT_AVATAR: string;
export type ParsedAvatar = { kind: "bot"; style: BotStyle; mood: BotMood } | { kind: "text"; text: string };
export declare function parseAvatar(avatar: string | null | undefined, name?: string): ParsedAvatar;
export declare function botAvatar(style: string, mood: string): string;
export declare function nextPose(current: number, count: number, random?: () => number): number;
