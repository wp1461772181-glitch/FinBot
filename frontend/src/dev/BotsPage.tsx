// Developer-only sample page (#/dev/kit/bots): the five bots that exist, side by side at size L, and one row of buttons that puts all of them in
// the same state at once (the first sketch of the A5 rehearsal stage). Copy is English on purpose (no i18n). The page runs the real parts
// (director, persona, painter); only the events come from buttons instead of a chat. In reduced motion it shows still frames, each with the
// face, gaze and badge of its pose.
import { useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { BotBody, type LiveHandle } from "@/components/bot/BotBody";
import { drive } from "@/components/bot/live-drive";
import { createDirector, type DirectorEvent, type DirectorView } from "../bloub-director.mjs";
import { resolveLook } from "../bloub-look.mjs";
import { PERSONA_PRESETS, derivePersona, type Persona } from "../bot-persona.mjs";
import { BOT_AVATAR_SIZE } from "../bot-sizes.mjs";

/** The five bots as the box has them (D6): id, name and the look each has stored (TeslaBot has none: its preset's recommended look shows). */
const BOTS = [
  { id: PERSONA_PRESETS[0]!.id, name: "FinBot", look: { shape: "cercle", color: "encre" } },
  { id: PERSONA_PRESETS[1]!.id, name: "TeslaBot", look: null },
  { id: PERSONA_PRESETS[2]!.id, name: "NewsBot", look: { shape: "nuage", color: "gris" } },
  { id: PERSONA_PRESETS[3]!.id, name: "AppleBot", look: { shape: "hexagone", color: "orange" } },
  { id: PERSONA_PRESETS[4]!.id, name: "ReportBot", look: { shape: "capsule", color: "violet" } }
];

const now = () => performance.now() / 1000;
type Sequence = ReadonlyArray<DirectorEvent>;
const START: Sequence = [{ type: "turn-start", quiet: true }];
/** What each button sends to every director. `reset` runs first. */
const SCENARIOS: Record<string, Sequence> = {
  idle: [],
  listening: [{ type: "phase", phase: "listening" }],
  thinking: START,
  tool: [...START, { type: "phase", phase: "tool" }],
  verify: [...START, { type: "phase", phase: "verify" }],
  answer: [...START, { type: "phase", phase: "answer" }],
  waiting: [...START, { type: "turn-end", outcome: "waiting" }],
  done: [...START, { type: "turn-end", outcome: "done" }],
  partial: [...START, { type: "turn-end", outcome: "partial" }],
  failed: [...START, { type: "turn-end", outcome: "error" }],
  offline: [{ type: "offline", value: true }]
};
const LABELS: Record<string, string> = { idle: "Idle", listening: "Listening", thinking: "Thinking", tool: "Tool", verify: "Verify", answer: "Answer", waiting: "Waiting for you", done: "Done", partial: "Partial", failed: "Failed", offline: "Offline", sleep: "Asleep" };
const ORDER = ["idle", "listening", "thinking", "tool", "verify", "answer", "waiting", "done", "partial", "failed", "offline", "sleep"];

const reducedMotion = () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

function reset(director: ReturnType<typeof createDirector>) {
  const t = now();
  director.send({ type: "turn-end", outcome: "cancel" }, t);
  director.send({ type: "waiting-clear" }, t);
  director.send({ type: "offline", value: false }, t);
  director.send({ type: "phase", phase: "idle" }, t);
}

export default function BotsPage() {
  const reduced = useMemo(reducedMotion, []);
  const personas = useMemo<Persona[]>(() => BOTS.map(bot => derivePersona({ id: bot.id, name: bot.name })), []);
  const handles = useRef<LiveHandle[]>([]);
  if (handles.current.length === 0) handles.current = BOTS.map((_, i) => ({ director: createDirector({ now: now(), reducedMotion: reduced, persona: personas[i] }), pointer: null, drive }));
  const [scenario, setScenario] = useState("idle");
  const [views, setViews] = useState<DirectorView[]>(() => handles.current.map(h => h.director.read(now())));

  const pick = (name: string) => {
    setScenario(name);
    handles.current.forEach((handle, i) => {
      if (name === "sleep") handle.director = createDirector({ now: now() - 61, reducedMotion: false, persona: personas[i] }); // 61 s of nothing: it falls asleep (also read for the still frame: a reduced-motion director never sleeps)
      else { reset(handle.director); for (const event of SCENARIOS[name] ?? []) handle.director.send(event, now()); }
      handle.wake?.();
    });
    if (reduced) setViews(handles.current.map(h => h.director.read(now())));
  };

  return <main className="min-h-screen space-y-8 bg-background p-6 text-foreground" data-kit-page data-testid="bots-page">
    <h1 className="text-xl font-semibold">Bots (dev only)</h1>
    <section aria-label="The five bots" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5" data-testid="bots-row">
      {BOTS.map((bot, i) => {
        const persona = personas[i]!, look = resolveLook(bot.id, "", bot.look, bot.name), view = views[i]!;
        return <figure key={bot.id} data-testid={`bot-sample-${bot.name}`} data-bot-color={look.color} className="flex flex-col items-center gap-3 rounded-lg border border-line bg-surface p-4">
          <span data-slot="bot-avatar" className="bot-orb" style={{ width: BOT_AVATAR_SIZE.hero, height: BOT_AVATAR_SIZE.hero }}>
            {reduced
              ? <BotBody size={BOT_AVATAR_SIZE.hero} shape={look.shape} color={look.color} state={view.state as never} frozenAt={0} expression={view.still} waiting={view.waitingForUser} dim={view.dim} gazeKind={view.gaze} tilt={view.tilt} />
              : <BotBody size={BOT_AVATAR_SIZE.hero} shape={look.shape} color={look.color} live={handles.current[i]} unlimited />}
          </span>
          <figcaption className="space-y-0.5 text-center text-sm">
            <strong className="block">{bot.name}</strong>
            <span data-field="archetype" className="block text-muted-foreground">{persona.archetype} · {persona.source}</span>
            <span data-field="tempo" className="block text-muted-foreground">tempo {persona.tempo} · {persona.easing}</span>
            <span data-field="gaze" className="block text-muted-foreground">rest gaze {persona.restGaze}</span>
            <span data-field="colour" className="block text-muted-foreground">{look.shape} · {look.color}</span>
          </figcaption>
        </figure>;
      })}
    </section>
    <section aria-label="State" className="flex flex-wrap gap-2" data-testid="bots-states">
      {ORDER.map(name => <Button key={name} type="button" size="sm" variant={scenario === name ? "default" : "outline"} aria-pressed={scenario === name} data-scenario={name} onClick={() => pick(name)}>{LABELS[name]}</Button>)}
    </section>
  </main>;
}
