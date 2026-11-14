// The "Line signature" block of the Bots sample page (#/dev/kit/bots): the six traces of thinking, the five carets and the closing line
// (done / partial / failed), side by side, each under the colour of the bot that wears it.  They are the real CSS (styles/bots-signature.css),
// picked the way the chat page picks them: data-trace / data-caret on a container.  `Replay` mounts them again from their first frame; the
// switch puts a container under data-motion="reduce" (the app-level hook A5's 关闭 level will use) so the still poses show.  English on purpose.
import { useState, type CSSProperties } from "react";
import { Button } from "@/components/ui/button";
import { DoneLine } from "@/app/chat/DoneLine";
import { CURSORS, TRACES, signatureOf } from "../signature.mjs";
import { derivePersona, PERSONA_PRESETS, type Persona } from "../bot-persona.mjs";
import { resolveLook } from "../bloub-look.mjs";

/** A bot of each kind to lend its colour and tempo: the five that exist, plus a custom bot for the generalist. */
const WEARERS: Array<{ trace: string; cursor: string; name: string; id: string; persona: Persona }> = [
  ...PERSONA_PRESETS.map(preset => ({ id: preset.id, name: preset.name, persona: derivePersona({ id: preset.id, name: preset.name }) })),
  { id: "custom-bot-1", name: "Custom bot", persona: derivePersona({ id: "custom-bot-1", name: "Custom bot" }) }
].map(w => ({ ...w, ...signatureOf(w.persona) }));
const colourOf = (w: { id: string; name: string }) => resolveLook(w.id, "", null, w.name).color;
const LABEL: Record<string, string> = { candles: "candles (lead)", streaks: "streaks (quick tracker)", steps: "steps (sentinel)", arc: "arc (calm tracker)", lines: "lines (reader)", drift: "drift (standard tracker)", orbit: "orbit (generalist)" };

export default function SignatureRow() {
  const [run, setRun] = useState(0);
  const [reduced, setReduced] = useState(false);
  const traces = TRACES.map(trace => WEARERS.find(w => w.trace === trace) ?? { ...WEARERS[0]!, trace, persona: { ...WEARERS[0]!.persona, auraVariant: "reticle" } });
  const cursors = CURSORS.map(cursor => WEARERS.find(w => w.cursor === cursor) ?? WEARERS[0]!);
  return <section aria-label="Line signature" data-testid="signature-row" data-motion={reduced ? "reduce" : undefined} className="space-y-4">
    <div className="flex flex-wrap items-center gap-2">
      <h2 className="text-lg font-semibold">Line signature</h2>
      <Button type="button" size="sm" variant="outline" data-testid="signature-replay" onClick={() => setRun(value => value + 1)}>Replay</Button>
      <Button type="button" size="sm" variant={reduced ? "default" : "outline"} aria-pressed={reduced} data-testid="signature-reduced" onClick={() => setReduced(value => !value)}>Reduced motion</Button>
    </div>
    <div key={run} className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7" data-testid="signature-traces">
        {traces.map(w => <figure key={w.trace} data-trace={w.trace} data-bot-color={colourOf(w)} style={{ "--bot-tempo": w.persona.tempo } as CSSProperties} data-testid={`trace-${w.trace}`}
          className="flex flex-col items-center gap-2 rounded-lg border border-line bg-surface px-3 py-4">
          <span className="think-trace" aria-hidden="true"><i /><i /><i /></span>
          <figcaption className="text-center text-xs text-muted-foreground">{LABEL[w.trace]}<br />tempo {w.persona.tempo}</figcaption>
        </figure>)}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:grid-cols-5" data-testid="signature-carets">
        {cursors.map(w => <figure key={w.cursor} data-caret={w.cursor} data-bot-color={colourOf(w)} style={{ "--bot-tempo": w.persona.tempo } as CSSProperties} data-testid={`caret-${w.cursor}`}
          className="rounded-lg border border-line bg-surface px-3 py-4">
          <div className="chat-prose" data-streaming=""><p>Revenue grew 12% from a year ago and the margin held</p></div>
          <figcaption className="pt-2 text-xs text-muted-foreground">{w.cursor} ({w.name})</figcaption>
        </figure>)}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="signature-lines">
        {(["done", "partial", "failed"] as const).map((state, k) => <figure key={state} data-bot-color={colourOf(WEARERS[k % WEARERS.length]!)} data-testid={`line-${state}`} className="space-y-3 rounded-lg border border-line bg-surface px-3 py-4">
          <p className="text-chat">An answer ends here.</p>
          <DoneLine state={state} />
          <figcaption className="text-xs text-muted-foreground">{state}{state === "failed" ? " (danger, still)" : ""}</figcaption>
        </figure>)}
      </div>
    </div>
  </section>;
}
