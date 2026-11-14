export const T: { ATTENTION: number; SUCCESS: number; ERROR: number; HOVER: number; CLICK: number; SLEEP_AFTER: number; DWELL: number; INTRO: number; PARTIAL: number; SLEEP_FREEZE: number; NUDGE: number; NUDGE_EVERY: number; NUDGE_MAX: number };
export const S: Record<string, string | string[]>;
/** How a turn ended. Only "done" and "error" play a stinger; "waiting" and "partial" are recorded in `DirectorView.ended`. */
export type TurnOutcome = "done" | "error" | "cancel" | "waiting" | "partial";
export type DirectorPhase = "waiting" | "thinking" | "tool" | "verify" | "answer" | "listening" | "idle";
export type DirectorEvent =
  | { type: "turn-start"; quiet?: boolean } | { type: "phase"; phase: DirectorPhase }
  | { type: "waiting-clear" } | { type: "hold" } | { type: "offline"; value: boolean }
  | { type: "turn-end"; outcome: TurnOutcome } | { type: "unread"; value: boolean }
  | { type: "hover"; value: boolean } | { type: "click" } | { type: "activity" } | { type: "arrive" }
  /** The bot standing here becomes another (design 6.7).  `at`: when the switch was asked for (the director's clock; default: now). `quiet`: the new bot is already working. `unread`: it has unread messages (the eyes glance at the divider after the handoff). */
  | { type: "handoff"; persona: Partial<DirectorPersona>; at?: number; quiet?: boolean; unread?: boolean }
  /** A switch was asked for (the click), the new line does not exist yet: the old aura leaves now.  `handoff` follows with the persona. */
  | { type: "handoff-begin"; at?: number }
  /** The same bot's personality changed (a late volatility, an override): swapped silently. */
  | { type: "persona"; persona: Partial<DirectorPersona> };
export interface HandoffView {
  /** leave: the old aura goes (persona still the old); swap: the new persona, the swirl, no aura; enter: the new aura comes in; settle: the swirl rings fade (the body is still coming to rest). */
  phase: "leave" | "swap" | "enter" | "settle";
  /** Real seconds since the switch was asked for, and since the phase's own beginning (for `enter`; the others count from the switch). */
  age: number; t: number;
  /** The aura variants of the bot that left and of the one now (or going to be) there; `quiet`: no swirl and no entrance. `carry`: the body pose a redirected handoff starts from. */
  from: string; to: string | null; quiet: boolean; carry: Record<string, number> | null }
export interface DirectorView { state: string; layer: "work" | "handoff" | "notify" | "reaction" | "life" | "idle";
  /** The pose behind the state: idle / listen / waiting / tool / verify / answer / hold (waiting for you) / offline / attention / stinger / handoff (the swirl) / glance (at the unread divider) / notify / reaction / sleep. */
  pose: string;
  follow: boolean; intro: boolean; expression: string; moodMorph: number;
  /** The face a still frame of this pose wears (reduced motion; `expression` stays calm there). */
  still: string;
  /** Where the eyes go: follow (the pointer) / ahead-right / scan / down / front are a persona's rest gazes; side / side-left / below / sweep (a tool runs: toward where the aura is) and below (listening, verifying) are work gazes. */
  gaze: "follow" | "ahead-right" | "scan" | "down" | "front" | "side" | "side-left" | "sweep" | "below";
  /** Degrees the whole body leans (the tracker's forward lean while resting). */
  tilt: number;
  /** The last turn ended waiting for you ("waiting": until the next turn starts or `waiting-clear`) or partially succeeded ("partial": for T.PARTIAL seconds); otherwise null. */
  ended: "waiting" | "partial" | null;
  /** The amber dot is up (the waiting-for-you pose). */
  waitingForUser: boolean;
  /** How the last turn ended (null until a turn has ended, and again once the next one starts) and the real seconds since: the aura plays its own end beat from these. */
  outcome: TurnOutcome | null; outcomeAge: number | null;
  /** Progress 0..1 of the partial nod (the body drops 4% and comes back), null when there is none. */
  nod: number | null;
  /** Offline: half the colour is taken out of the (frozen) idle frame. */
  dim: boolean;
  /** Nothing moves any more (asleep for T.SLEEP_FREEZE, offline, a settled waiting-for-you): draw this frame and stop the loop until something is sent. */
  frozen: boolean;
  /** The handoff under way (null when none). */
  handoff: HandoffView | null;
  tempo: number; easing: "smooth" | "spring" | "step"; archetype: string;
  /** The persona's aura variant (src/aura/index.mjs). */
  aura: string }
export interface Director { send(event: DirectorEvent, now: number): void; read(now: number): DirectorView }
export interface DirectorPersona { archetype: string; tempo: number; easing: "smooth" | "spring" | "step"; restGaze: string; auraVariant: string }
/** The state table of one personality (the default `S` plus that archetype's click reactions). */
export function bodyTable(persona?: Partial<DirectorPersona>): Record<string, string | string[]>;
export function createDirector(options?: { now?: number; reducedMotion?: boolean; persona?: Partial<DirectorPersona> }): Director;
export function shouldArrive(seen: Set<string>, botId: string | null | undefined, reducedMotion: boolean, switching?: boolean): boolean;
export function turnPhase(chatState: string, messages: ReadonlyArray<{ role?: string; content?: string; tool_trace?: ReadonlyArray<{ status?: string }> }> | undefined): "waiting" | "tool" | "verify" | "answer" | null;
export function turnTransition(prev: string, next: string, messages: ReadonlyArray<{ role?: string; status?: string; clarification?: unknown }> | undefined): DirectorEvent | null;
