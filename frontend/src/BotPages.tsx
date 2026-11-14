// Bots (personal agent, second edition): the bot list hook and the two page icons.  The right rail and the new-bot dialog moved to
// BotSidePanel.tsx and the server model catalog card to app/settings/ModelCatalogCard.tsx in P3.1, so the sidebar loads only this file.
// A bot never holds a key: it names a catalog model, and the catalog says only configured / missing.
import { useCallback, useEffect, useState } from "react";
import { listBots, type Bot } from "./api";
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


/** 例行任务: a calendar with a clock.  An SVG, not a glyph: the rail's font drew ✉ as nothing (Levi: 没有图标). */
export function RoutineIcon() {
  return <svg className="routine-icon" viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    <path d="M8 3v3M16 3v3M4 9h11M13 21H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v4" />
    <circle cx="17.5" cy="17.5" r="4" /><path d="M17.5 15.8v1.9l1.2 1" />
  </svg>;
}

/** 新闻源: a newspaper, drawn as an SVG for the same reason as the routine icon. */
export function NewsIcon() {
  return <svg className="news-icon" viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    <path d="M4 5h13v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5Z" /><path d="M17 9h3v8a2 2 0 0 1-2 2h-1" />
    <path d="M7.5 9h6M7.5 12.5h6M7.5 16h4" />
  </svg>;
}
