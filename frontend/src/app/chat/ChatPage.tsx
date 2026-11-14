import { useEffect, useRef, useState, type ReactNode } from "react";
import { type Bot } from "../../api";
import { LegacyFrame } from "../../LegacyFrame";
import { resolveLook } from "../../bloub-look.mjs";
import { useLocale } from "../../i18n";
import { Button } from "@/components/ui/button";
import { HistoryList } from "./HistoryList";
import { ChatHeader } from "./ChatHeader";
import { Thread } from "./Thread";
import { Composer } from "./Composer";
import { useChat } from "./ChatSessionProvider";

// With the right panel: beside the thread from xl up (a third column; half / full are the panel's own width buttons), over it below xl
// (a sheet over the thread's right edge, the whole width on a phone).  The panel's root is `.bot-side`, one level down in a marker.
const SIDE_LAYOUT = [
  "xl:grid-cols-[minmax(0,1fr)_340px] xl:data-[side-width=half]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:data-[side-width=full]:grid-cols-[minmax(0,1fr)]",
  "xl:data-[side-width=full]:[&>:not(.bot-side-host)]:hidden",
  "max-xl:[&_.bot-side]:absolute max-xl:[&_.bot-side]:inset-y-0 max-xl:[&_.bot-side]:right-0 max-xl:[&_.bot-side]:z-overlay max-xl:[&_.bot-side]:w-[min(360px,100%)]",
  "max-xl:[&_.bot-side]:bg-background max-xl:[&_.bot-side]:p-4 max-xl:[&_.bot-side]:shadow-pop max-lg:[&_.bot-side]:w-full",
].join(" ");
const SIDE_OPEN_KEY = "market-evidence-agent:bot-side-open:v1";
/** The right panel's first state when nothing is stored: open where it sits beside the thread (xl and up), closed where it would cover it. */
const sideDefault = () => window.matchMedia?.("(min-width: 1280px)").matches ?? true;

/**
 * The chat page (design 4.2): the header, then the history list (no bot) | the thread with its composer | the bot's right panel.
 * `agent-page` stays on the root only for its custom properties (--c-*), which the old parts still embedded read.  The thread is at most 760px wide and centred; the 2px line on top of it is the bot's signature colour.  The right panel is still
 * the old component (工作区 / 档案): beside the thread from xl up, over it below that.
 */
export function ChatPage({ bot, side, onTurnSettled, onBotChanged, openSide }: { bot?: Bot | null; side?: ReactNode; onTurnSettled?: () => void; onBotChanged?: () => void; openSide?: boolean }) {
  const { t } = useLocale(), c = useChat();
  // A finished turn changes the bot's last line (and gives a new bot its conversation): tell the list.
  const wasSending = useRef(false);
  useEffect(() => { if (c.state === "sending") { wasSending.current = true; return; } if (wasSending.current) { wasSending.current = false; onTurnSettled?.(); } }, [c.state]); // eslint-disable-line react-hooks/exhaustive-deps
  const [historyOpen, setHistoryOpen] = useState(false);
  // A bot's right panel folds away so the thread can use the full width; the choice is kept.
  const [sideOpen, setSideOpen] = useState(() => { if (openSide) return true; try { const stored = localStorage.getItem(SIDE_OPEN_KEY); return stored === null ? sideDefault() : stored === "1"; } catch { return sideDefault(); } });
  const toggleSide = () => setSideOpen(open => { const next = !open; try { localStorage.setItem(SIDE_OPEN_KEY, next ? "1" : "0"); } catch { /* optional preference */ } return next; });
  // The history drawer (narrow screens, no bot) closes with Esc.
  useEffect(() => { if (!historyOpen) return; const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setHistoryOpen(false); }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [historyOpen]);
  const draftBox = useRef<HTMLTextAreaElement>(null);
  const color = bot ? resolveLook(bot.id, bot.avatar, bot.look).color : undefined;
  const hasSide = Boolean(side);
  return <main data-slot="chat-page" data-testid="chat-page" data-bot-color={color} aria-labelledby="chat-title" className="agent-page flex min-h-0 flex-1 flex-col bg-background">
    <ChatHeader bot={bot} side={side} sideOpen={sideOpen} toggleSide={toggleSide} historyOpen={historyOpen} setHistoryOpen={setHistoryOpen} />
    {/* `agent-layout is-bot` are the right panel's own hooks (it writes data-side-width on the closest .agent-layout); the grid is set here. */}
    <div data-testid="chat-body" className={`agent-layout${hasSide ? " is-bot" : ""} relative grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] gap-0 ${bot ? "" : "lg:grid-cols-[264px_minmax(0,1fr)]"} ${hasSide ? SIDE_LAYOUT : ""}`}>
      <HistoryList bot={bot} historyOpen={historyOpen} setHistoryOpen={setHistoryOpen} />
      <div data-testid="chat-column" className="flex min-h-0 min-w-0 flex-col">
        <div aria-hidden="true" data-testid="bot-line" className={`h-0.5 shrink-0 ${bot ? "bg-bot" : "bg-line"}`} />
        {c.archiveView && <div data-testid="archive-banner" className="mx-auto mt-3 flex w-[calc(100%-2rem)] max-w-[760px] flex-wrap items-center gap-2 rounded-md border border-line bg-sunken px-3 py-2 text-small text-ink-2">
          <span className="mr-auto">{t("本地归档只读查看")}</span>
          <Button type="button" variant="outline" size="sm" onClick={c.returnLive}>{t("返回当前对话")}</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => { c.returnLive(); c.clear(); }}>{t("新建对话")}</Button>
        </div>}
        <Thread bot={bot} draftBox={draftBox} />
        <Composer bot={bot} draftBox={draftBox} onBotChanged={onBotChanged} />
      </div>
      {side && <div className={`bot-side-host ${sideOpen ? "contents" : "hidden"}`}><LegacyFrame>{side}</LegacyFrame></div>}
    </div>
  </main>;
}
