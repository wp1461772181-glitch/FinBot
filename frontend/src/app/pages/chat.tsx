import { Suspense, lazy, useEffect, useRef } from "react";
import { Navigate, useParams } from "react-router";
import { DelayedSkeleton, SkeletonCard, SkeletonMessages } from "@/components/state/Skeleton";
import { ChatPage } from "../chat/ChatPage";
import { useOpenConversation, useSelectBot } from "../chat/ChatSessionProvider";
import { translatePhrase } from "../../i18n";
import { OptionalChunk } from "../../OptionalChunk";
import { isRecordId, paths } from "../../routes.mjs";
import type { Bot } from "../../api";
import { useWorkspace } from "../workspace";

// The bot's workspace cards and profile form (the 工作区 and 档案 tabs of the right panel) are only needed once a bot page is open: their own chunk, fetched on demand.
const BotWorkspacePane = lazy(() => import("../../BotSidePanel").then((module) => ({ default: module.BotWorkspacePane })));
const BotProfilePane = lazy(() => import("../../BotSidePanel").then((module) => ({ default: module.BotProfilePane })));

/** What stands in a panel tab while its chunk comes: nothing for the first 400ms, then a card's shape. */
const paneFallback = <DelayedSkeleton><SkeletonCard /></DelayedSkeleton>;

/** A bot's page: its one line in the middle, the right panel beside it (来源 / 过程 / 工作区 / 档案).  Its turns go out with only its id. */
function BotPage({ bot, profile = false }: { bot: Bot; profile?: boolean }) {
  const ws = useWorkspace();
  const selectBot = useSelectBot();
  useEffect(() => { void selectBot(bot); }, [bot]); // eslint-disable-line react-hooks/exhaustive-deps
  const changed = () => void ws.bots.reload();
  return <ChatPage bot={bot} onTurnSettled={changed} onBotChanged={changed} openProfile={profile}
    workspace={(wide) => <OptionalChunk><Suspense fallback={paneFallback}><BotWorkspacePane key={bot.id} bot={bot} symbol={ws.symbol} watchlist={ws.symbols} onSelectSymbol={ws.setPreferredSymbol} wide={wide}
      onOpenCompany={(ticker, section) => ws.openCompany(ticker, section === "forecast" ? "forecast" : "overview")} /></Suspense></OptionalChunk>}
    profile={<OptionalChunk><Suspense fallback={paneFallback}><BotProfilePane key={bot.id} bot={bot} onChanged={changed} onDeleted={() => { changed(); ws.go("agent"); }} /></Suspense></OptionalChunk>} />;
}

/** The bot list is still on its way: the thread's own skeleton (after 400ms); a bot that is not there says so. */
const loading = <main className="mx-auto w-full max-w-[760px] flex-1 p-6"><DelayedSkeleton><SkeletonMessages /></DelayedSkeleton></main>;
const missing = (text: string) => <main className="mx-auto w-full max-w-[760px] flex-1 p-6"><p role="status" className="text-body text-muted-foreground">{translatePhrase(text)}</p></main>;

/** /chat: the default bot's line (owner), or the plain conversation (guest). */
export function ChatRoute() {
  const ws = useWorkspace();
  if (ws.personal && !ws.bots.loaded) return loading;
  if (ws.personal && ws.bots.defaultBot) return <BotPage bot={ws.bots.defaultBot} />;
  return <ChatPage />;
}

/** /chat/:botId and /chat/:botId/settings (the same page with the 档案 tab up front; P5.1 makes it a page of its own). */
export function ChatBotRoute({ profile = false }: { profile?: boolean }) {
  const ws = useWorkspace();
  const botId = (useParams().botId ?? "").toLowerCase();
  const bot = ws.personal ? ws.bots.bots.find(b => b.id === botId) ?? null : null;
  if (bot) return <BotPage key={bot.id} bot={bot} profile={profile} />;
  return ws.bots.loaded ? missing("bot 不存在或已删除。") : loading;
}

/** A conversation outside any bot's line (the memory page, a run record, recall_conversations link to it): read and continued as before. */
export function ChatConversationRoute() {
  const ws = useWorkspace();
  const conversationId = useParams().conversationId ?? "";
  const selectBot = useSelectBot(), selectRef = useRef(selectBot); selectRef.current = selectBot;
  const openConversation = useOpenConversation(), openRef = useRef(openConversation); openRef.current = openConversation;
  const valid = isRecordId(conversationId);
  useEffect(() => {
    if (!valid) return;
    void selectRef.current(null).then(() => openRef.current(conversationId)).catch(() => { /* the panel reports a conversation it cannot restore */ });
  }, [conversationId, valid]);
  if (!valid) return <Navigate to={paths.chat()} replace />;
  return <ChatPage />;
}

/** /chat/history: the conversation panel with no bot, whose left column is the history list. */
export function ChatHistoryRoute() {
  const ws = useWorkspace();
  const selectBot = useSelectBot(), selectRef = useRef(selectBot); selectRef.current = selectBot;
  useEffect(() => { void selectRef.current(null).catch(() => { /* the panel reports it */ }); }, []);
  return <ChatPage />;
}
