// Bots (personal agent, second edition): the bot list hook and the two page icons.  The right rail and the new-bot dialog moved to
// BotSidePanel.tsx and the server model catalog card to app/settings/ModelCatalogCard.tsx in P3.1, so the sidebar loads only this file.
// A bot never holds a key: it names a catalog model, and the catalog says only configured / missing.
import { useCallback, useEffect, useState } from "react";
import { listBots, type Bot } from "./api/bots";
import { message } from "./bot-message";

/** The owner's bots, read once and again after each change.  Guests have none. */
export function useBots(enabled: boolean) {
  const [bots, setBots] = useState<Bot[]>([]), [loaded, setLoaded] = useState(!enabled), [error, setError] = useState("");
  const reload = useCallback(async () => {
    if (!enabled) return;
    try { const value = await listBots(); setBots(value.bots); setError(""); }
    catch (err) { setError(message(err, "bot 列表暂时无法读取。")); }
    finally { setLoaded(true); }
  }, [enabled]);
  useEffect(() => { void reload(); }, [reload]);
  return { bots, loaded, error, reload, defaultBot: bots.find(b => b.is_default) ?? null };
}
