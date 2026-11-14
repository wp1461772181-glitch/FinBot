// Writes the bot's personality onto the chat page for the parts of the line that are drawn in CSS (design 6.6: the trace of thinking, the
// caret, the closing line): data-archetype, data-aura-variant and --bot-tempo on the nearest [data-slot=chat-page].  It is a lazy chunk of
// its own (the rules live in bot-persona.mjs, which is the avatar's too, so the two share one downloaded module) and does not wait for, or
// depend on, the avatar; until it has run the line is drawn with the default (generalist) signature.
import { useLayoutEffect, useRef } from "react";
import type { PersonaBot } from "../../bot-persona.mjs";
import { signatureOf } from "../../signature.mjs";
import { usePersona } from "./use-persona";

export default function PersonaAttrs({ bot }: { bot: PersonaBot }) {
  const persona = usePersona(bot);
  const anchor = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const page = anchor.current?.closest<HTMLElement>("[data-slot=chat-page]");
    if (!page) return;
    const { trace, cursor } = signatureOf(persona);
    page.dataset.archetype = persona.archetype;
    page.dataset.auraVariant = persona.auraVariant;
    page.dataset.trace = trace;
    page.dataset.caret = cursor;
    page.style.setProperty("--bot-tempo", String(persona.tempo));
    return () => { delete page.dataset.archetype; delete page.dataset.auraVariant; page.dataset.trace = "orbit"; page.dataset.caret = "bar"; }; // --bot-tempo stays: the avatar writes the same value
  }, [persona.archetype, persona.auraVariant, persona.tempo]);
  return <span ref={anchor} hidden />;
}
