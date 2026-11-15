export declare const HANDOFF: Readonly<{ OUT: number; SWAP: number; COLOR: number; ENTER_AT: number; ENTER: number; SWIRL_END: number; STAGGER_FROM: number; STAGGER_STEP: number; STAGGER_COUNT: number; FOCUS_BY: number; GLANCE: number; CROSSFADE: number; SLIDE_PX: number; RAPID: number; NEVER: number }>;
export declare function handoffDirection(order: readonly string[] | null | undefined, fromId: string | null | undefined, toId: string | null | undefined): -1 | 0 | 1;
export type HandoffSource = "pointer" | "drawer" | "keyboard" | "route";
export declare const SOURCES: readonly HandoffSource[];
export declare function sourceOfClick(detail: number, inDrawer?: boolean): HandoffSource;
export declare const movesFocus: (source: HandoffSource | undefined) => boolean;
