export declare function staggerDelay(index: number, count: number, options?: { reduced?: boolean }): number | null;
export declare const isRapid: (previousAt: number | null | undefined, at: number) => boolean;
export type LineMotion = "slide" | "rise" | "crossfade";
export declare function lineMotion(options?: { reduced?: boolean; level?: string; phone?: boolean }): LineMotion;
export declare const playsSwirl: (options?: { reduced?: boolean; level?: string }) => boolean;
