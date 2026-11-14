export const T: { ATTENTION: number; SUCCESS: number; ERROR: number; HOVER: number; CLICK: number; SLEEP_AFTER: number; DWELL: number; INTRO: number; PARTIAL: number };
export const S: Record<string, string | string[]>;
/** How a turn ended. Only "done" and "error" play a stinger; "waiting" and "partial" are recorded in `DirectorView.ended`. */
export type TurnOutcome = "done" | "error" | "cancel" | "waiting" | "partial";
export type DirectorEvent =
  | { type: "turn-start"; quiet?: boolean } | { type: "phase"; phase: "waiting" | "tool" | "answer" }
  | { type: "turn-end"; outcome: TurnOutcome } | { type: "unread"; value: boolean }
  | { type: "hover"; value: boolean } | { type: "click" } | { type: "activity" } | { type: "arrive" };
export interface DirectorView { state: string; layer: "work" | "notify" | "reaction" | "life" | "idle"; follow: boolean; intro: boolean; expression: string; moodMorph: number;
  /** The last turn ended waiting for you ("waiting": until the next turn starts) or partially succeeded ("partial": for T.PARTIAL seconds); otherwise null. No picture is attached to it yet. */
  ended: "waiting" | "partial" | null }
export interface Director { send(event: DirectorEvent, now: number): void; read(now: number): DirectorView }
export function createDirector(options?: { now?: number; reducedMotion?: boolean }): Director;
export function shouldArrive(seen: Set<string>, botId: string | null | undefined, reducedMotion: boolean): boolean;
export function turnPhase(chatState: string, messages: ReadonlyArray<{ role?: string; content?: string; tool_trace?: ReadonlyArray<{ status?: string }> }> | undefined): "waiting" | "tool" | "answer" | null;
export function turnTransition(prev: string, next: string, messages: ReadonlyArray<{ role?: string; status?: string; clarification?: unknown }> | undefined): DirectorEvent | null;
