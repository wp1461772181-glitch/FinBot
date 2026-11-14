import { lazy, useEffect, useRef } from "react";
import { Navigate, useParams } from "react-router";
import { ChatPage } from "../chat/ChatPage";
import { useOpenConversation, useSelectBot } from "../chat/ChatSessionProvider";
import { translatePhrase } from "../../i18n";
import { OptionalChunk } from "../../OptionalChunk";
import { isRecordId, paths } from "../../routes.mjs";
import type { Bot } from "../../api";
import { useWorkspace } from "../workspace";

// The bot's right rail (工作区 / 档案) is only needed once a bot page is open: its own chunk, fetched on demand.
const BotSide = lazy(() => import("../../BotSidePanel").then((module) => ({ default: module.BotSide })));

/** A bot's page: its one line in the middle, 工作区 / 档案 on the right.  Its turns go out with only its id. */
function BotPage({ bot, profile = false }: { bot: Bot; profile?: boolean }) {
  const ws = useWorkspace();
  const selectBot = useSelectBot();
  useEffect(() => { void selectBot(bot); }, [bot]); // eslint-disable-line react-hooks/exhaustive-deps
  const changed = () => void ws.bots.reload();
  return <ChatPage bot={bot} onTurnSettled={changed} onBotChanged={changed} openSide={profile}
    side={<OptionalChunk><BotSide key={bot.id} bot={bot} symbol={ws.symbol} watchlist={ws.symbols} onSelectSymbol={ws.setPreferredSymbol} initialTab={profile ? "profile" : "workspace"}
      onOpenCompany={(ticker, section) => ws.openCompany(ticker, section === "forecast" ? "forecast" : "overview")} onChanged={changed} onDeleted={() => { changed(); ws.go("agent"); }} /></OptionalChunk>} />;
}

const waiting = (text: string) => <main className="workspace"><p role="status">{translatePhrase(text)}</p></main>;

/** /chat: the default bot's line (owner), or the plain conversation (guest). */
export function ChatRoute() {
  const ws = useWorkspace();
  if (ws.personal && !ws.bots.loaded) return waiting("正在读取…");
  if (ws.personal && ws.bots.defaultBot) return <BotPage bot={ws.bots.defaultBot} />;
  return <ChatPage />;
}

/** /chat/:botId and /chat/:botId/settings (the same page with the 档案 tab up front; P5.1 makes it a page of its own). */
export function ChatBotRoute({ profile = false }: { profile?: boolean }) {
  const ws = useWorkspace();
  const botId = (useParams().botId ?? "").toLowerCase();
  const bot = ws.personal ? ws.bots.bots.find(b => b.id === botId) ?? null : null;
  if (bot) return <BotPage key={bot.id} bot={bot} profile={profile} />;
  return waiting(ws.bots.loaded ? "bot 不存在或已删除。" : "正在读取…");
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
