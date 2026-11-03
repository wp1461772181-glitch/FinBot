export declare const BLOUB_SHAPES: string[];
export declare const BLOUB_COLORS: string[];
export declare function hashString(value: string): number;
export declare function bloubLook(id: string | null | undefined, avatar: string | null | undefined): { shape: string; color: string };
export declare function bloubState(flags?: { running?: boolean; unread?: boolean }): "idle" | "orbit" | "notify";
export declare function faceLook(style: string, mood: string): { shape: string; color: string };
