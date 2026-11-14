export type Phase = "idle" | "listening" | "thinking" | "tool" | "verify" | "answer";
export declare const PHASES: Phase[];
type Msg = {
  role?: string; content?: string; status?: string; clarification?: unknown; card_at?: number;
  tool_trace?: ReadonlyArray<{ name?: string; status?: string; result?: unknown }>; trace?: ReadonlyArray<{ kind?: string; status?: string }>;
  failure?: { network?: boolean };
};
export interface TurnSignal { phase: Phase; units: number; offline: boolean }
export declare function unitsOf(message: Msg | null | undefined): number;
export declare function turnSignal(input?: { chatState?: string; messages?: ReadonlyArray<Msg>; draft?: string; composerFocused?: boolean; offline?: boolean }): TurnSignal;
export declare function isOffline(input?: { backendDown?: boolean; chatState?: string; messages?: ReadonlyArray<Msg> }): boolean;
export declare function awaiting(messages: ReadonlyArray<Msg> | undefined, now: number): { waiting: boolean; expiresAt: number | null };
export declare function announcement(input?: { phase?: Phase; waiting?: boolean; offline?: boolean; tool?: string | null }): { phrase: string; detail: string | null } | null;
export declare function runningTool(messages: ReadonlyArray<Msg> | undefined): string | null;
