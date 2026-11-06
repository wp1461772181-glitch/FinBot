export declare const EFFORT_LEVELS: readonly ["none", "minimal", "low", "medium", "high", "xhigh", "max"];
export declare function effortLabel(value: string | null | undefined): string;
export declare function effortChoices(current: string | null | undefined): { value: string | null; label: string; checked: boolean; disabled: false }[];
export declare function modelChoices(catalog: { default: string | null; models: { name: string; display_name: string; model: string; key_status: string }[] }, current: string | null | undefined): { value: string | null; label: string; checked: boolean; keyMissing?: boolean }[];
export declare function patchFor(kind: "model" | "effort", value: string | null): { model: string | null } | { reasoning_effort: string | null };
export declare function badgeText(bot: { model: string | null; reasoning_effort: string | null }, t?: (text: string) => string): string;
