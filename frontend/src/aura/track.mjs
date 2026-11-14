// From the director's view to the aura's input (design 6.2: the units come from data, the beats from the turn).  The tracker is the one piece
// of memory around the aura: when the current state began (and what the one before it left), when each unit came back, whether the turn
// went through a check.  Pure: it is given the clock (`clock` the avatar's own, tempo already multiplied in; `now` real seconds) and
// does not read one.
import { endLength } from "./shared.mjs";

/** Reduced motion has no clock: a finished turn shows its closed shape for this many real seconds (the check badge of design 6.9 goes the
 * same moment); a failed one stays until the next turn, as the "!" still frame and the error bar do. */
export const STILL_FINISH_SECONDS = 2;
const WORKING = new Set(["think", "tool", "verify", "answer"]);
const ENDING = new Set(["done", "partial", "error"]);
/** How long a cancelled turn's aura takes to leave. */
const CANCEL_SECONDS = 0.32;

/** The aura's phase for a director view.  `still`: reduced motion (no clock: the end shapes use STILL_FINISH_SECONDS). */
export function auraPhaseOf(view, { still = false } = {}) {
  let phase;
  switch (view.pose) {
    case "attention": case "waiting": phase = "think"; break;
    case "tool": case "verify": case "answer": case "listen": case "hold": phase = view.pose; break;
    case "stinger": phase = view.outcome === "error" ? "error" : "done"; break;
    case "notify": phase = "unread"; break;
    case "sleep": case "offline": phase = view.pose; break;
    default: phase = "idle";
  }
  // The turn is over but the director has already moved on (a partial nod is 0.6 s, reduced motion has no stinger): the aura keeps its beat.
  if ((phase === "idle" || phase === "listen") && view.outcome && view.outcomeAge !== null) {
    const age = view.outcomeAge;
    if (view.outcome === "cancel") return age < CANCEL_SECONDS && !still ? "cancel" : phase;
    if (view.outcome === "error") return still || age < endLength("error") ? "error" : phase;
    if (view.outcome === "done" || view.outcome === "partial") return age < (still ? STILL_FINISH_SECONDS : endLength(view.outcome)) ? view.outcome : phase;
  }
  return phase;
}

/** The input of the aura for a reduced-motion still frame: the state's static shape (the aura function ignores time). */
export function stillInput(view, units, verified) {
  return { phase: auraPhaseOf(view, { still: true }), t: 0, units, verified, reduced: true, easing: view.easing, tempo: view.tempo, waiting: view.waitingForUser, outcome: view.outcome };
}

export function createTracker() {
  let phase = null, since = 0, shown = 0, seen = 0, turnStart = null, verified = false, frozenUnits = 0;
  let born = [], bornAt = [];
  let settled = null;
  return {
    /** One frame.  Returns the aura input (without the size: `R`, `tier`). */
    step({ clock, now, view, units }) {
      const next = auraPhaseOf(view);
      if (next !== phase) {
        settled = phase ? { phase, units: shown, t: Math.max(0, clock - since) } : null;
        // a turn begins when work starts after a state that was not part of one
        if (WORKING.has(next) && !(phase && (WORKING.has(phase) || phase === "hold"))) { born = []; bornAt = []; seen = 0; turnStart = clock; verified = false; }
        if (ENDING.has(next)) frozenUnits = shown;
        phase = next; since = clock;
      }
      const live = ENDING.has(phase) ? frozenUnits : units;
      if (!ENDING.has(phase)) {
        for (let i = seen; i < live; i++) { const known = turnStart !== null; born[i] = known ? clock - turnStart : NaN; bornAt[i] = known ? now : -Infinity; } // found already there (a restored conversation): settled, no arrival
        if (live < seen) { born.length = live; bornAt.length = live; }
        seen = live;
      }
      if (phase === "verify") verified = true;
      shown = live;
      return {
        phase, t: Math.max(0, clock - since), units: live, settled, verified, easing: view.easing, tempo: view.tempo, outcome: view.outcome,
        waiting: view.waitingForUser, ages: bornAt.map(at => now - at), born, turn: turnStart === null ? undefined : clock - turnStart
      };
    },
    /** Seconds on the avatar's clock since the current state began (the gaze follows the moving point with it). */
    sinceEntered: clock => Math.max(0, clock - since)
  };
}
