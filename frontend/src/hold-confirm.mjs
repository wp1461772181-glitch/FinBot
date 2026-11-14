// Press-and-hold to confirm (design 5.4, for what cannot be undone).  Pure state machine; the button feeds it events and a clock.
//
//   idle ──press──▶ holding ──(held long enough)──▶ done
//     ▲               │ release / leave
//     └───────────────┘
// Two ways round the hold, each with the same effect and each reachable without holding anything:
//   · reduced motion: a hold has no progress to animate, so it becomes press twice (the first press arms, the second confirms);
//   · a click that came with no press before it (a screen reader's "activate", voice control): the same press-twice.
// An armed button disarms after `armMs` or when focus leaves it.

export const HOLD_MS = 1000;
export const ARM_MS = 4000;

export const initialHold = () => ({ phase: "idle", since: 0, via: null });

/** Progress 0..1 of a hold at `now`. */
export function holdProgress(state, now, holdMs = HOLD_MS) {
  if (state.phase === "done") return 1;
  if (state.phase !== "holding") return 0;
  return Math.min(1, Math.max(0, (now - state.since) / holdMs));
}

/**
 * One event in, the next state out.  Events: { type: "press", via: "pointer" | "key", now },
 * { type: "release", now }, { type: "tick", now }, { type: "click", now } (a click with no press before it),
 * { type: "blur" }.  `options.reducedMotion` turns holds into press-twice.
 */
export function stepHold(state, event, { holdMs = HOLD_MS, armMs = ARM_MS, reducedMotion = false } = {}) {
  switch (event.type) {
    case "press":
      if (state.phase === "done") return state;
      if (reducedMotion) return state.phase === "armed" && event.now - state.since <= armMs ? { phase: "done", since: event.now, via: event.via } : { phase: "armed", since: event.now, via: event.via };
      if (state.phase === "holding") return state;            // key auto-repeat
      return { phase: "holding", since: event.now, via: event.via };
    case "release":
      return state.phase === "holding" ? initialHold() : state;
    case "tick":
      if (state.phase === "holding" && event.now - state.since >= holdMs) return { ...state, phase: "done" };
      if (state.phase === "armed" && event.now - state.since > armMs) return initialHold();
      return state;
    case "click":
      // Reached with no press before it: confirm in two steps.
      if (state.phase === "armed" && event.now - state.since <= armMs) return { phase: "done", since: event.now, via: "click" };
      if (state.phase === "idle") return { phase: "armed", since: event.now, via: "click" };
      return state;
    case "blur":
      return state.phase === "done" ? state : initialHold();
    default:
      return state;
  }
}
