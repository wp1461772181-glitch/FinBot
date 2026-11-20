// The chat page's right panel, 工作区 tab: the bot's data cards.  A chunk of its own (app/pages/chat.tsx loads it on demand), so the chat page does not carry the eight cards' code.
import { useEffect, useRef, useState } from "react";
import type { Bot } from "../../../api/bots";
import { botSymbol, storeBotSymbol } from "../../../workspace-cards.mjs";
import { WorkspaceTab } from "./WorkspaceTab";

/**
 * The pane of the panel (app/chat/ContextPanel.tsx holds the tabs, the width, 来源 and 过程).  The current stock is kept per bot and follows the page's stock, as the old right rail kept it.
 */
export function BotWorkspacePane({ bot, symbol, watchlist = [], onSelectSymbol, wide }: { bot: Bot; symbol: string; watchlist?: string[]; onSelectSymbol?: (symbol: string) => void; wide: boolean }) {
  const [current, setCurrent] = useState(() => botSymbol(bot, symbol));
  const seenGlobal = useRef(symbol);
  useEffect(() => { if (current !== symbol) onSelectSymbol?.(current); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (symbol === seenGlobal.current) return;
    seenGlobal.current = symbol;
    if (symbol !== current) { setCurrent(symbol); storeBotSymbol(bot.id, symbol); }
  }, [symbol]); // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (next: string) => { const clean = storeBotSymbol(bot.id, next); if (!clean) return; setCurrent(clean); seenGlobal.current = clean; onSelectSymbol?.(clean); };
  return <WorkspaceTab bot={bot} symbol={current} watchlist={watchlist} wide={wide} onPickSymbol={pick} />;
}
