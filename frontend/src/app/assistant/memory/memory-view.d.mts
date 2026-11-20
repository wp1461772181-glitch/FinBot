import type { ProfileBot, ProfileItem } from "../../../api/memory";
export declare function memoryTab(value: string | null | undefined): "profile" | "recall";
export declare const KIND_LABELS: Record<ProfileItem["kind"], string>;
export declare const KINDS: readonly ProfileItem["kind"][];
export declare const MAX_TEXT: number;
export declare function isInferred(item: ProfileItem): boolean;
export declare function scopeChoices(item: ProfileItem, bots: ProfileBot[]): { bots: ProfileBot[]; gone: boolean };
export declare function canSaveEdit(text: string): boolean;
