import { lazy, useEffect, useRef, useState, type ReactNode } from "react";
import { type Bot } from "../../api/bots";
import { resolveLook } from "../../bloub-look.mjs";
import { useLocale } from "../../i18n";
import { Button } from "@/components/ui/button";
import { OptionalChunk } from "../../OptionalChunk";
import { HistoryList } from "./HistoryList";
import { ChatHeader } from "./ChatHeader";
import { Thread } from "./Thread";
import { Composer } from "./Composer";
import { ContextPanel } from "./ContextPanel";
import { PanelProvider } from "./panel-context";
import { useChat } from "./ChatSessionProvider";
import { useKeyboardInset } from "./use-keyboard-inset";
import { usePhone } from "./use-media";
import { currentIntent } from "./handoff-intent";
import { PresenceSlot } from "@/components/bot/presence-dock";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";

// The persona's part of the line's look (trace of thinking, caret, closing line): data attributes written onto the page by a chunk of its own.
const PersonaAttrs = lazy(() => import("@/components/bot/PersonaAttrs"));

/**
 * The chat page (design 4.2): the header, then the history list (no bot) | the thread with its composer | the right panel.
 * `agent-page` stays on the root only for its custom properties (--c-*), which the old parts still embedded (the confirmation card, the
 * bot's workspace and profile) read.  The thread is at most 760px wide and centred; the 2px line on top of it is the bot's signature colour.
 * The right panel is a column from xl up (the reader drags its width) and lies over the thread below that.
 * `workspace` and `profile` are the bot's own panes (a page with no bot has neither: the panel then holds only 来源 and 过程).
 */
export function ChatPage({ bot, workspace, profile, onTurnSettled, onBotChanged, openProfile }: { bot?: Bot | null; workspace?: (wide: boolean) => ReactNode; profile?: ReactNode; onTurnSettled?: () => void; onBotChanged?: () => void; openProfile?: boolean }) {
  return <PanelProvider hasWorkspace={Boolean(workspace)} hasProfile={Boolean(profile)} startOnProfile={Boolean(openProfile)}>
    <ChatPageBody bot={bot} workspace={workspace} profile={profile} onTurnSettled={onTurnSettled} onBotChanged={onBotChanged} />
  </PanelProvider>;
}

const PAGE_CLASS = "agent-page flex min-h-0 flex-1 flex-col bg-background";

function ChatPageBody({ bot, workspace, profile, onTurnSettled, onBotChanged }: { bot?: Bot | null; workspace?: (wide: boolean) => ReactNode; profile?: ReactNode; onTurnSettled?: () => void; onBotChanged?: () => void }) {
  const { t } = useLocale(), c = useChat();
  // A finished turn changes the bot's last line (and gives a new bot its conversation): tell the list.
  const wasSending = useRef(false);
  useEffect(() => { if (c.state === "sending") { wasSending.current = true; return; } if (wasSending.current) { wasSending.current = false; onTurnSettled?.(); } }, [c.state]); // eslint-disable-line react-hooks/exhaustive-deps
  const [historyOpen, setHistoryOpen] = useState(false);
  // The history drawer (narrow screens, no bot) closes with Esc.
  useEffect(() => { if (!historyOpen) return; const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setHistoryOpen(false); }; window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [historyOpen]);
  const draftBox = useRef<HTMLTextAreaElement>(null);
  const color = bot ? resolveLook(bot.id, bot.avatar, bot.look, bot.name).color : undefined;
  // The signature colour travels from the bot that was left to this one (design 6.7, 200 ms: the custom properties are registered colours with a
  // transition, bots-handoff.css): this page is new, so it starts with the old colour and takes its own on the next frame.  No switch, no travel.
  const [shown, setShown] = useState(() => (bot ? currentIntent(bot.id)?.fromColor : null) ?? color);
  useEffect(() => { if (shown === color) return; const id = requestAnimationFrame(() => setShown(color)); return () => cancelAnimationFrame(id); }, [color, shown]);
  // A phone's on-screen keyboard that covers the page (iOS) lifts the composer by as much as it covers; where the browser resizes the layout instead, this is 0.
  const keyboard = useKeyboardInset(usePhone());
  // The page is mounted before the session has moved to this bot's line (pages/chat.tsx does that in a layout effect, before the first paint): the render in
  // between has nothing to show, so it draws nothing of the page (the line it would draw is the one before, gone a moment later).
  if (bot && c.bot?.id !== bot.id) return <main data-slot="chat-page" data-bot-color={shown} className={PAGE_CLASS}><PresenceSlot size={BOT_AVATAR_SIZE.title} /></main>; // (the avatar's place stays occupied: it is one body that outlives the pages)
  return <main data-slot="chat-page" data-testid="chat-page" data-bot-color={shown} data-trace="orbit" data-caret="bar" aria-labelledby="chat-title" style={keyboard ? { paddingBottom: keyboard } : undefined} className={PAGE_CLASS}>
    {bot && <OptionalChunk><PersonaAttrs bot={bot} /></OptionalChunk>}
    <ChatHeader bot={bot} historyOpen={historyOpen} setHistoryOpen={setHistoryOpen} />
    <div data-testid="chat-body" className="relative flex min-h-0 flex-1">
      <div className={`grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(0,1fr)] gap-0 ${bot ? "" : "lg:grid-cols-[264px_minmax(0,1fr)]"}`}>
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
      </div>
      <ContextPanel bot={bot} workspace={workspace} profile={profile} />
    </div>
  </main>;
}
