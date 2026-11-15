export declare const SPLIT: RegExp;
export declare function readTags(text: string, current: readonly string[], options?: { normalize?: (raw: string) => string; validate?: (item: string) => boolean; max?: number }): { add: string[]; invalid: string[]; cut: boolean };
