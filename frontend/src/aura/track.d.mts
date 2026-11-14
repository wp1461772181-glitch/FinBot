import type { AuraEasing, AuraInput, AuraPhase } from "./shared.mjs";
import type { DirectorView } from "../bloub-director.mjs";
export const STILL_FINISH_SECONDS: number;
export function auraPhaseOf(view: Pick<DirectorView, "pose" | "outcome" | "outcomeAge">, options?: { still?: boolean }): AuraPhase;
/** The input for a reduced-motion still frame (no `R` / `tier`: the caller adds the size). */
export function stillInput(view: DirectorView, units: number, verified: boolean): Omit<AuraInput, "R" | "tier">;
export interface Tracker {
  /** One frame: the aura input without the size.  `clock` is the avatar's own (tempo multiplied in), `now` real seconds. */
  step(frame: { clock: number; now: number; view: DirectorView; units: number }): Omit<AuraInput, "R" | "tier"> & { easing: AuraEasing };
  sinceEntered(clock: number): number;
}
export function createTracker(): Tracker;
