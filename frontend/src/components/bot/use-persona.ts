// A bot's personality for the avatar: derived from its record, pinned for the five existing bots, overridden by what the reader chose in
// this browser. A tracker bot with a company and no stored volatility looks the price history up ONCE (the same call the workspace price
// card makes); if that gives nothing it falls back to the id hash and does not try again.
import { useEffect, useMemo, useState } from "react";
import { getV2Prices } from "../../api/prices";
import { annualizedVolatility, archetypeOf, derivePersona, presetFor, readOverrides, readVolatility, trackedSymbol, writeVolatility, type Persona, type PersonaBot } from "../../bot-persona.mjs";

/** Bot + symbol pairs already asked this page session: no retry, no second request while the first is out. */
const asked = new Set<string>();
const storage = () => { try { return window.localStorage; } catch { return null; } };

export function usePersona(bot: PersonaBot | null | undefined): Persona {
  const id = bot?.id ?? "", symbol = trackedSymbol(bot);
  const needsLookup = Boolean(bot) && !presetFor(bot) && archetypeOf(bot) === "tracker" && Boolean(symbol);
  const [volatility, setVolatility] = useState<number | null>(() => (needsLookup && symbol ? readVolatility(storage(), id, symbol) : null));
  useEffect(() => {
    if (!needsLookup || !symbol) { setVolatility(null); return; }
    const stored = readVolatility(storage(), id, symbol);
    setVolatility(stored);
    const key = `${id}:${symbol}`;
    if (stored !== null || asked.has(key)) return;
    asked.add(key);
    let live = true;
    getV2Prices(symbol).then(
      reply => {
        const value = annualizedVolatility(reply.price_history.candles.map(candle => candle.close));
        if (value === null) return;
        writeVolatility(storage(), id, symbol, value);
        if (live) setVolatility(value);
      },
      () => { /* nothing came back: the hash decides, and it stays that way for this page session */ }
    );
    return () => { live = false; };
  }, [id, symbol, needsLookup]);
  const overrides = useMemo(() => readOverrides(storage(), id), [id]);
  const template = bot?.template, isDefault = bot?.is_default, name = bot?.name, company = bot?.default_company?.symbol;
  return useMemo(() => derivePersona(bot, { volatility, overrides }), [id, template, isDefault, name, company, symbol, volatility, overrides]); // eslint-disable-line react-hooks/exhaustive-deps
}
