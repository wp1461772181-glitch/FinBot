// The "Handoff" block of the Bots sample page (#/dev/kit/bots): one live avatar that becomes another bot, the way the chat header's does
// (design 6.7): the same director, the same body, the same `drive`; only the events come from buttons.  From / to are rows of buttons (the six
// kinds of bot: the five that exist and a custom one, which has the generalist's aura), `Switch` plays from -> to, `Rapid x3` clicks three
// different bots 100 ms apart, `Reduced motion` makes the stage a still frame.  `window.__handoffStage` lets the film tool (tools/shots/handoff-film.mjs)
// reset the stage to a bot and start a switch on a clock it controls.  English on purpose.
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { BotBody, type LiveHandle, type WornLook } from "@/components/bot/BotBody";
import { drive } from "@/components/bot/live-drive";
import { createDirector } from "../bloub-director.mjs";
import { resolveLook } from "../bloub-look.mjs";
import { PERSONA_PRESETS, derivePersona, type Persona } from "../bot-persona.mjs";

const SIZE = 144;
const PEOPLE = [
  { id: PERSONA_PRESETS[0]!.id, name: "FinBot", look: { shape: "cercle", color: "encre" } },
  { id: PERSONA_PRESETS[1]!.id, name: "TeslaBot", look: null },
  { id: PERSONA_PRESETS[2]!.id, name: "NewsBot", look: { shape: "nuage", color: "gris" } },
  { id: PERSONA_PRESETS[3]!.id, name: "AppleBot", look: { shape: "hexagone", color: "orange" } },
  { id: PERSONA_PRESETS[4]!.id, name: "ReportBot", look: { shape: "capsule", color: "violet" } },
  { id: "custom-bot-1", name: "Custom bot", look: { shape: "galet", color: "turquoise" } }
];
const nowSec = () => performance.now() / 1000;
const lookOf = (i: number): WornLook => { const p = PEOPLE[i]!, l = resolveLook(p.id, "", p.look, p.name); return { shape: l.shape, color: l.color }; };

export default function HandoffRow() {
  const personas = useMemo<Persona[]>(() => PEOPLE.map(p => derivePersona({ id: p.id, name: p.name })), []);
  const [from, setFrom] = useState(0), [to, setTo] = useState(1), [reduced, setReduced] = useState(false), [at, setAt] = useState(0);
  const [worn, setWorn] = useState<WornLook>(() => lookOf(0));
  const stage = useRef<{ handle: LiveHandle; reduced: boolean; at: number } | null>(null);
  const build = (index: number): LiveHandle => {
    const director = createDirector({ now: nowSec(), reducedMotion: reduced, persona: personas[index] });
    return { director, pointer: null, units: 0, drive, look: { want: lookOf(index), worn: lookOf(index), onWear: setWorn } };
  };
  if (!stage.current || stage.current.reduced !== reduced) stage.current = { handle: build(from), reduced, at: -1 };
  const handle = stage.current.handle;

  /** Stand the stage on bot `index` with nothing under way (a new director: no state from before). */
  const stand = (index: number) => {
    stage.current = { handle: build(index), reduced, at: stage.current?.at ?? -1 };
    setFrom(index); setWorn(lookOf(index)); setAt(n => n + 1);
  };
  /** Ask the stage to become bot `index` now (what a click on a bot row does). */
  const become = (index: number) => {
    const h = stage.current!.handle;
    h.look!.want = lookOf(index); h.look!.onWear = setWorn;
    h.director.send({ type: "handoff", persona: personas[index], at: nowSec() }, nowSec());
    if (reduced) setWorn(lookOf(index));
    setTo(index); h.wake?.(); setAt(n => n + 1);
  };
  useEffect(() => {
    (window as unknown as { __handoffStage?: unknown }).__handoffStage = { stand, become, names: PEOPLE.map(p => p.name) };
    return () => { delete (window as unknown as { __handoffStage?: unknown }).__handoffStage; };
  });
  const rapid = () => {
    const order = [(to + 1) % PEOPLE.length, (to + 2) % PEOPLE.length, (to + 3) % PEOPLE.length];
    order.forEach((index, k) => window.setTimeout(() => become(index), k * 100));
  };
  const pickers = (label: string, value: number, set: (i: number) => void, testid: string) => <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1" data-testid={testid}>
    <span className="w-10 text-sm text-muted-foreground">{label}</span>
    {PEOPLE.map((p, i) => <Button key={p.id} type="button" size="sm" variant={value === i ? "default" : "outline"} aria-pressed={value === i} data-bot={p.name} onClick={() => set(i)}>{p.name}</Button>)}
  </div>;
  return <section aria-label="Handoff" className="space-y-4" data-testid="handoff-row">
    <h2 className="text-lg font-semibold">Handoff</h2>
    <div className="space-y-2">
      {pickers("From", from, stand, "handoff-from")}
      {pickers("To", to, setTo, "handoff-to")}
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" data-testid="handoff-switch" onClick={() => { stand(from); window.setTimeout(() => become(to), 60); }}>Switch</Button>
        <Button type="button" size="sm" variant="outline" data-testid="handoff-rapid" onClick={rapid}>Rapid x3</Button>
        <Button type="button" size="sm" variant={reduced ? "default" : "outline"} aria-pressed={reduced} data-testid="handoff-reduced" onClick={() => setReduced(value => !value)}>Reduced motion</Button>
      </div>
    </div>
    <figure data-testid="handoff-stage" data-key={at} data-bot-color={worn.color} className="flex w-fit flex-col items-center gap-2 rounded-lg border border-line bg-surface px-16 py-16">
      <span data-slot="bot-avatar" className="bot-orb" style={{ width: SIZE, height: SIZE }}>
        {reduced
          ? <BotBody size={SIZE} shape={lookOf(to).shape} color={lookOf(to).color} frozenAt={0} />
          : <BotBody size={SIZE} shape={worn.shape} color={worn.color} live={handle} unlimited />}
      </span>
      <figcaption className="pt-12 text-center text-xs text-muted-foreground">{PEOPLE[from]!.name} → {PEOPLE[to]!.name}</figcaption>
    </figure>
  </section>;
}
