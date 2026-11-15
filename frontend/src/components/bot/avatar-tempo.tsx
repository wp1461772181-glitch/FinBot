// The tempo of every bot in a list, for the ring that turns around an answering avatar (period = 1.2 s / tempo, design 6.4 / 6.6).  The rules
// that give a bot its tempo are the persona's (bot-persona.mjs, a chunk the lists must not carry), so a provider fetches that chunk after
// the first paint and hands the numbers down; until then, and for a bot it has no number for, the ring turns at the base period.
import { createContext, lazy, useContext, useState, type ReactNode } from "react";
import { OptionalChunk } from "../../OptionalChunk";
import type { PersonaBot } from "../../bot-persona.mjs";

const Tempos = createContext<Record<string, number>>({});
const TempoSource = lazy(() => import("./TempoSource"));

/** The tempo of one bot (1 when unknown). */
export function useAvatarTempo(botId: string | undefined): number {
  const all = useContext(Tempos);
  return (botId && all[botId]) || 1;
}

export function AvatarTempoProvider({ bots, children }: { bots: ReadonlyArray<PersonaBot & { id: string }>; children: ReactNode }) {
  const [tempos, setTempos] = useState<Record<string, number>>({});
  return <Tempos.Provider value={tempos}>
    {children}
    {bots.length > 0 && <OptionalChunk><TempoSource bots={bots} onChange={setTempos} /></OptionalChunk>}
  </Tempos.Provider>;
}
