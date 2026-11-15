// The scripted turns the rehearsal (settings, "试演台") and the Bots sample page (#/dev/kit/bots) play to an avatar: not a chat, just the events the
// chat would have sent the director, and how many tool calls have come back.  One table for both pages (design 6.9: "点哪个演哪个").
// `idle` .. `failed` are the buttons of the rehearsal; `tool5`, `empty`, `offline` are the sample page's extras.
import type { DirectorEvent } from "../../bloub-director.mjs";
import type { LiveHandle } from "./BotBody";

/** One step of a scenario: at `at` seconds, tell the directors `events` and/or set how many tool calls have come back. */
export interface Step { at: number; events?: ReadonlyArray<DirectorEvent>; units?: number }
export interface Scenario { steps: ReadonlyArray<Step>; /** the end state (reduced motion shows it at once) */ units: number; checked: boolean; caption?: string }

const START: DirectorEvent = { type: "turn-start", quiet: true };
const TOOL: DirectorEvent = { type: "phase", phase: "tool" };
const VERIFY: DirectorEvent = { type: "phase", phase: "verify" };
const calls = (n: number): Step[] => Array.from({ length: n }, (_, i) => ({ at: 0.6 + i * 0.7, units: i + 1 }));
/** A whole turn up to the check: three calls come back, then the evidence is checked. */
const toCheck: Step[] = [{ at: 0, events: [START, TOOL] }, ...calls(3), { at: 2.7, events: [VERIFY] }];
const end = (outcome: "done" | "error" | "partial" | "waiting", at = 4.2): Step => ({ at, events: [{ type: "turn-end", outcome }] });

export const SCENARIOS: Record<string, Scenario> = {
  idle: { steps: [], units: 0, checked: false },
  listening: { steps: [{ at: 0, events: [{ type: "phase", phase: "listening" }] }], units: 0, checked: false },
  thinking: { steps: [{ at: 0, events: [START] }], units: 0, checked: false },
  tool1: { steps: [{ at: 0, events: [START, TOOL] }, ...calls(1)], units: 1, checked: false },
  tool: { steps: [{ at: 0, events: [START, TOOL] }, ...calls(3)], units: 3, checked: false },
  tool3: { steps: [{ at: 0, events: [START, TOOL] }, ...calls(3)], units: 3, checked: false },
  tool5: { steps: [{ at: 0, events: [START, TOOL] }, ...calls(5)], units: 5, checked: false },
  // three calls: the second came back empty, so the units go 1, 1, 2 (not 1, 2, 3)
  empty: { steps: [{ at: 0, events: [START, TOOL] }, { at: 0.6, units: 1 }, { at: 1.3 }, { at: 2.0, units: 2 }], units: 2, checked: false, caption: "3 calls, 1 empty: 2 units" },
  verify: { steps: toCheck, units: 3, checked: true },
  answer: { steps: [...toCheck, { at: 3.6, events: [{ type: "phase", phase: "answer" }] }], units: 3, checked: true },
  waiting: { steps: [...toCheck, end("waiting", 3.6)], units: 3, checked: true },
  done: { steps: [...toCheck, end("done")], units: 3, checked: true },
  partial: { steps: [...toCheck, end("partial")], units: 3, checked: true },
  failed: { steps: [...toCheck, end("error")], units: 3, checked: true },
  offline: { steps: [{ at: 0, events: [{ type: "offline", value: true }] }], units: 0, checked: false }
};

/** Put a director back to rest: no turn, nothing waiting, online, idle. */
export function resetDirector(director: LiveHandle["director"], t: number) {
  director.send({ type: "turn-end", outcome: "cancel" }, t);
  director.send({ type: "waiting-clear" }, t);
  director.send({ type: "offline", value: false }, t);
  director.send({ type: "phase", phase: "idle" }, t);
}

/**
 * Play scenario `name` to these avatars: each is put back to rest, then the scenario's events go to its director on the scenario's clock (the steps
 * that are due at once now, the later ones by timer; `timers` collects the timer ids so the owner can cancel them).  `reduced`: there is no clock, every
 * step is applied at once and the scenario's end state is what the still frame shows.  Returns the scenario.
 */
export function playScenario(name: string, handles: ReadonlyArray<LiveHandle>, { now, reduced, timers }: { now: () => number; reduced: boolean; timers: number[] }): Scenario {
  for (const handle of handles) { handle.units = 0; resetDirector(handle.director, now()); handle.wake?.(); }
  const plan = SCENARIOS[name] ?? SCENARIOS.idle!;
  const apply = (step: Step) => {
    for (const handle of handles) {
      for (const event of step.events ?? []) handle.director.send(event, now());
      if (step.units !== undefined) handle.units = step.units;
      handle.wake?.();
    }
  };
  for (const step of plan.steps) {
    if (reduced || step.at <= 0) apply(step); else timers.push(window.setTimeout(() => apply(step), step.at * 1000));
  }
  return plan;
}
