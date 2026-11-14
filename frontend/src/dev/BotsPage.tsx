// Developer-only sample page (#/dev/kit/bots): the five bots that exist, side by side at size L (and again at size M), and buttons that put all of
// them in the same state at once: the four beats of the aura (collect: tool x1 / x3 / x5 / an empty result; check; output; wait; close: done /
// partial; break: failed). Copy is English on purpose (no i18n). The page runs the real parts (director, persona, tracker, aura, painter);
// only the events come from buttons instead of a chat. In reduced motion (the system setting, or the switch on the page) it shows still frames:
// the face, gaze, badge and aura shape of each state. `window.__auraFilm` (below) draws one bot's aura at an exact moment of a scripted turn:
// the evidence film of the four beats is built from it (tools/shots/aura-film.mjs).
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import SignatureRow from "./SignatureRow";
import { BotBody, type LiveHandle } from "@/components/bot/BotBody";
import { drawAura } from "@/components/bot/aura-paint";
import { drive } from "@/components/bot/live-drive";
import { COLOR_BY_ID } from "../bloub/skins";
import { RAYON } from "../bloub/repere";
import { createDirector, type DirectorEvent, type DirectorView } from "../bloub-director.mjs";
import { resolveLook } from "../bloub-look.mjs";
import { PERSONA_PRESETS, derivePersona, type Persona } from "../bot-persona.mjs";
import { BOT_AVATAR_SIZE, tierOf } from "../bot-sizes.mjs";
import { auraFor } from "../aura/index.mjs";
import { bodyMotion } from "../aura/motion.mjs";
import { auraPhaseOf, createTracker, stillInput } from "../aura/track.mjs";

/** The five bots as the box has them (D6): id, name and the look each has stored (TeslaBot has none: its preset's recommended look shows). */
const BOTS = [
  { id: PERSONA_PRESETS[0]!.id, name: "FinBot", look: { shape: "cercle", color: "encre" } },
  { id: PERSONA_PRESETS[1]!.id, name: "TeslaBot", look: null },
  { id: PERSONA_PRESETS[2]!.id, name: "NewsBot", look: { shape: "nuage", color: "gris" } },
  { id: PERSONA_PRESETS[3]!.id, name: "AppleBot", look: { shape: "hexagone", color: "orange" } },
  { id: PERSONA_PRESETS[4]!.id, name: "ReportBot", look: { shape: "capsule", color: "violet" } }
];
const SIZE_L = 144, SIZE_M = BOT_AVATAR_SIZE.title;

const now = () => performance.now() / 1000;
/** One step of a scenario: at `at` seconds, tell the directors `events` and/or set how many tool calls have come back. */
interface Step { at: number; events?: ReadonlyArray<DirectorEvent>; units?: number }
interface Scenario { steps: ReadonlyArray<Step>; /** the end state (reduced motion shows it at once) */ units: number; checked: boolean; caption?: string }
const START: DirectorEvent = { type: "turn-start", quiet: true };
const TOOL: DirectorEvent = { type: "phase", phase: "tool" };
const VERIFY: DirectorEvent = { type: "phase", phase: "verify" };
const calls = (n: number): Step[] => Array.from({ length: n }, (_, i) => ({ at: 0.6 + i * 0.7, units: i + 1 }));
/** A whole turn up to the check: three calls come back, then the evidence is checked. */
const toCheck: Step[] = [{ at: 0, events: [START, TOOL] }, ...calls(3), { at: 2.7, events: [VERIFY] }];
const end = (outcome: "done" | "error" | "partial" | "waiting", at = 4.2): Step => ({ at, events: [{ type: "turn-end", outcome }] });
const SCENARIOS: Record<string, Scenario> = {
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
const LABELS: Record<string, string> = {
  idle: "Idle", listening: "Listening", thinking: "Thinking", tool1: "Tool x1", tool3: "Tool x3", tool5: "Tool x5", empty: "Empty result", verify: "Verify", answer: "Answer",
  waiting: "Waiting for you", done: "Done", partial: "Partial", failed: "Failed", offline: "Offline", sleep: "Asleep"
};
const ORDER = ["idle", "listening", "thinking", "tool1", "tool3", "tool5", "empty", "verify", "answer", "waiting", "done", "partial", "failed", "offline", "sleep"];

const reducedMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

function reset(director: ReturnType<typeof createDirector>) {
  const t = now();
  director.send({ type: "turn-end", outcome: "cancel" }, t);
  director.send({ type: "waiting-clear" }, t);
  director.send({ type: "offline", value: false }, t);
  director.send({ type: "phase", phase: "idle" }, t);
}

interface Row { handles: LiveHandle[] }
const inkOf = (color: string) => (color === "encre" ? "var(--me-ink, #0a0a0c)" : COLOR_BY_ID.get(color)?.hex ?? "#0a0a0c");

export default function BotsPage() {
  const systemReduced = useMemo(reducedMotion, []);
  const [reduced, setReduced] = useState(systemReduced);
  const personas = useMemo<Persona[]>(() => BOTS.map(bot => derivePersona({ id: bot.id, name: bot.name })), []);
  const rows = useRef<{ L: Row; M: Row; reduced: boolean } | null>(null);
  const makeRow = (): Row => ({ handles: BOTS.map((_, i) => ({ director: createDirector({ now: now(), reducedMotion: reduced, persona: personas[i] }), pointer: null, units: 0, drive })) });
  if (!rows.current || rows.current.reduced !== reduced) rows.current = { L: makeRow(), M: makeRow(), reduced };
  const [scenario, setScenario] = useState("idle");
  const [still, setStill] = useState<{ views: DirectorView[]; units: number; checked: boolean }>(() => ({ views: rows.current!.L.handles.map(h => h.director.read(now())), units: 0, checked: false }));
  const timers = useRef<number[]>([]);
  const clearTimers = () => { timers.current.forEach(id => window.clearTimeout(id)); timers.current = []; };
  useEffect(() => clearTimers, []);
  useEffect(() => { setScenario("idle"); setStill({ views: rows.current!.L.handles.map(h => h.director.read(now())), units: 0, checked: false }); }, [reduced]);

  const all = () => [...rows.current!.L.handles, ...rows.current!.M.handles];
  const personaOf = (i: number) => personas[i % BOTS.length]!;
  const pick = (name: string) => {
    clearTimers();
    setScenario(name);
    const sets = all();
    sets.forEach((handle, k) => {
      handle.units = 0;
      if (name === "sleep") handle.director = createDirector({ now: now() - 61, reducedMotion: false, persona: personaOf(k) }); // 61 s of nothing: it falls asleep (also read for the still frame: a reduced-motion director never sleeps)
      else reset(handle.director);
      handle.wake?.();
    });
    const plan = SCENARIOS[name] ?? SCENARIOS.idle!;
    const apply = (step: Step) => {
      for (const handle of sets) {
        for (const event of step.events ?? []) handle.director.send(event, now());
        if (step.units !== undefined) handle.units = step.units;
        handle.wake?.();
      }
    };
    if (reduced) {
      // still frames: every event at once, the turn's end state; a finished turn shows its closed shape (outcomeAge 0 below)
      for (const step of plan.steps) apply(step);
      if (name === "sleep") sets.forEach(handle => { handle.units = 0; });
      setStill({ views: rows.current!.L.handles.map(h => h.director.read(now())), units: plan.units, checked: plan.checked });
      return;
    }
    for (const step of plan.steps) {
      if (step.at <= 0) apply(step); else timers.current.push(window.setTimeout(() => apply(step), step.at * 1000));
    }
  };

  // The evidence film: one bot's aura at an exact moment of a scripted turn (the real director and tracker, simulated on explicit times).
  const filmHosts = useRef<(SVGGElement | null)[]>([]);
  useEffect(() => {
    const frame = (bot: string, T: number, ending: "done" | "error" | "partial", tier: "L" | "M" = "L") => {
      const i = BOTS.findIndex(b => b.name === bot), persona = personas[i]!;
      const director = createDirector({ now: 0, persona }), tracker = createTracker();
      const at = { calls: [1.0, 1.7, 2.4], verify: 3.1, end: 4.4 }; // the first tool stays unheard for the director's dwell (0.6 s) after the turn starts at 0.2
      const sent = { start: false, tool: false, verify: false, end: false };
      let clock = 0, input = tracker.step({ clock, now: 0, view: director.read(0), units: 0 });
      for (let t = 0; t <= T + 1e-9; t += 1 / 60) {
        if (!sent.start && t >= 0.2) { director.send({ type: "turn-start", quiet: true }, t); sent.start = true; }
        if (!sent.tool && t >= 0.3) { director.send(TOOL, t); sent.tool = true; }
        if (!sent.verify && t >= at.verify) { director.send(VERIFY, t); sent.verify = true; }
        if (!sent.end && t >= at.end) { director.send({ type: "turn-end", outcome: ending }, t); sent.end = true; }
        clock += (1 / 60) * persona.tempo;
        const units = at.calls.filter(c => t >= c).length;
        input = tracker.step({ clock, now: t, view: director.read(t), units });
      }
      const host = filmHosts.current[i];
      if (!host) return null;
      const color = resolveLook(BOTS[i]!.id, "", BOTS[i]!.look, bot).color;
      drawAura(host, auraFor(personas[i]!.auraVariant)({ ...input, R: RAYON, tier }), { ink: inkOf(color) }, input.phase);
      return { phase: input.phase, units: host.getAttribute("data-aura-units"), form: host.getAttribute("data-aura-form") };
    };
    (window as unknown as { __auraFilm?: unknown }).__auraFilm = { frame, endsAt: 4.4, bots: BOTS.map(b => b.name) };
    return () => { delete (window as unknown as { __auraFilm?: unknown }).__auraFilm; };
  }, [personas]);

  const figure = (i: number, size: number, tier: "L" | "M") => {
    const bot = BOTS[i]!, look = resolveLook(bot.id, "", bot.look, bot.name);
    const row = tier === "L" ? rows.current!.L : rows.current!.M, handle = row.handles[i]!;
    const view = still.views[i]!;
    // reduced motion: the aura is the static shape of the state; a finished turn shows its closed form
    const auraStill = reduced ? (host: SVGGElement, paint: { ink: string }) => {
      const v = view.outcome === "done" || view.outcome === "partial" ? { ...view, outcomeAge: 0 } : view;
      const input = stillInput(v, still.units, still.checked);
      drawAura(host, auraFor(personas[i]!.auraVariant)({ ...input, R: RAYON, tier: tierOf(size) }), paint, input.phase);
    } : undefined;
    const tilt = view.tilt + (reduced ? bodyMotion({ variant: personas[i]!.auraVariant, phase: auraPhaseOf(view, { still: true }), reduced: true }).tilt : 0);
    return <span data-slot="bot-avatar" className="bot-orb" style={{ width: size, height: size }}>
      {reduced
        ? <BotBody size={size} shape={look.shape} color={look.color} state={view.state as never} frozenAt={0} expression={view.still} waiting={view.waitingForUser} dim={view.dim} gazeKind={view.gaze} tilt={tilt} auraStill={auraStill} />
        : <BotBody size={size} shape={look.shape} color={look.color} live={handle} unlimited />}
    </span>;
  };

  return <main className="min-h-screen space-y-8 bg-background p-6 text-foreground" data-kit-page data-testid="bots-page">
    <h1 className="text-xl font-semibold">Bots (dev only)</h1>
    <section aria-label="State" className="flex flex-wrap items-center gap-2" data-testid="bots-states">
      {ORDER.map(name => <Button key={name} type="button" size="sm" variant={scenario === name || (name === "tool3" && scenario === "tool") ? "default" : "outline"} aria-pressed={scenario === name} data-scenario={name} onClick={() => pick(name)}>{LABELS[name]}</Button>)}
      <Button type="button" size="sm" variant={reduced ? "default" : "outline"} aria-pressed={reduced} data-testid="reduced-toggle" onClick={() => setReduced(value => !value)}>Reduced motion</Button>
    </section>
    <section aria-label="The five bots" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5" data-testid="bots-row">
      {BOTS.map((bot, i) => {
        const persona = personas[i]!, look = resolveLook(bot.id, "", bot.look, bot.name);
        return <figure key={bot.id} data-testid={`bot-sample-${bot.name}`} data-bot-color={look.color} className="flex flex-col items-center gap-3 rounded-lg border border-line bg-surface px-4 py-16">
          {figure(i, SIZE_L, "L")}
          <figcaption className="space-y-0.5 pt-12 text-center text-sm">
            <strong className="block">{bot.name}</strong>
            <span data-field="archetype" className="block text-muted-foreground">{persona.archetype} · {persona.source}</span>
            <span data-field="tempo" className="block text-muted-foreground">tempo {persona.tempo} · {persona.easing}</span>
            <span data-field="gaze" className="block text-muted-foreground">rest gaze {persona.restGaze}</span>
            <span data-field="aura" className="block text-muted-foreground">aura {persona.auraVariant}</span>
            <span data-field="colour" className="block text-muted-foreground">{look.shape} · {look.color}</span>
            {SCENARIOS[scenario]?.caption ? <span className="block text-muted-foreground">{SCENARIOS[scenario]!.caption}</span> : null}
          </figcaption>
        </figure>;
      })}
    </section>
    <section aria-label="Tier M" className="grid grid-cols-5 gap-4" data-testid="bots-row-m">
      {BOTS.map((bot, i) => {
        const look = resolveLook(bot.id, "", bot.look, bot.name);
        return <figure key={bot.id} data-testid={`bot-sample-m-${bot.name}`} data-bot-color={look.color} className="flex flex-col items-center gap-2 rounded-lg border border-line bg-surface px-4 py-8">
          {figure(i, SIZE_M, "M")}
          <figcaption className="text-center text-xs text-muted-foreground">{bot.name} · M</figcaption>
        </figure>;
      })}
    </section>
    <section aria-label="Film" className="grid grid-cols-3 gap-4" data-testid="bots-film">
      {BOTS.map((bot, i) => {
        const look = resolveLook(bot.id, "", bot.look, bot.name);
        return <figure key={bot.id} data-testid={`film-${bot.name}`} data-bot-color={look.color} className="flex flex-col items-center gap-2 rounded-lg border border-line bg-surface px-4 py-16">
          <span data-slot="bot-avatar" className="bot-orb" style={{ width: SIZE_L, height: SIZE_L }}>
            <BotBody size={SIZE_L} shape={look.shape} color={look.color} frozenAt={0} auraStill={host => { filmHosts.current[i] = host; }} />
          </span>
          <figcaption className="pt-12 text-center text-xs text-muted-foreground">{bot.name} · film frame</figcaption>
        </figure>;
      })}
    </section>
    <SignatureRow />
  </main>;
}
