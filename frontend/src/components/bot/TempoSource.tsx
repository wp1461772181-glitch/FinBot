// The lazy half of avatar-tempo.tsx: reads each bot's persona (the pinned five, or derived; this browser's override on top; a tracker's stored
// volatility if there is one, never a request) and reports the tempos.  Renders nothing.
import { useEffect } from "react";
import { derivePersona, readOverrides, readVolatility, trackedSymbol, type PersonaBot } from "../../bot-persona.mjs";

const storage = () => { try { return window.localStorage; } catch { return null; } };

export default function TempoSource({ bots, onChange }: { bots: ReadonlyArray<PersonaBot & { id: string }>; onChange: (update: (previous: Record<string, number>) => Record<string, number>) => void }) {
  useEffect(() => {
    const store = storage(), next: Record<string, number> = {};
    for (const bot of bots) {
      const symbol = trackedSymbol(bot);
      next[bot.id] = derivePersona(bot, { volatility: symbol ? readVolatility(store, bot.id, symbol) : null, overrides: readOverrides(store, bot.id) }).tempo;
    }
    onChange(previous => {
      const same = Object.keys(next).length === Object.keys(previous).length && Object.keys(next).every(id => previous[id] === next[id]);
      return same ? previous : next;
    });
  }, [bots, onChange]);
  return null;
}
