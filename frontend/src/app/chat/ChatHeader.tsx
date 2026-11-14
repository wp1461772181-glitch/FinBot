// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { LiveBotOrb } from "../../LiveBotOrb";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { type ReactNode, type Dispatch, type SetStateAction } from "react";
import { type Bot } from "../../api";
import { useLocale } from "../../i18n";
import { useChat } from "./ChatSessionProvider";

function PanelIcon(){return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M15 4v16"/></svg>}

export function ChatHeader({ bot, side, sideOpen, toggleSide, historyOpen, setHistoryOpen }: { bot?: Bot | null; side?: ReactNode; sideOpen: boolean; toggleSide: () => void; historyOpen: boolean; setHistoryOpen: Dispatch<SetStateAction<boolean>> }) {
  const { t } = useLocale(), c = useChat();
  return (
    <header className="workspace-heading agent-page-heading">
      {bot?<div className="agent-title-row"><LiveBotOrb key={bot.id} avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.title} chatState={c.state} messages={c.messages} unread={bot.unread>0||c.freshExternal} onAcknowledge={c.ackExternal} /><h1 id="agent-chat-title">{bot.name}</h1>{bot.title&&<small className="bot-title">{bot.title}</small>}</div>
        :<div className="agent-title-row"><button type="button" className="mobile-history-toggle secondary-action" aria-expanded={historyOpen} onClick={()=>setHistoryOpen(x=>!x)}>{t("历史对话")}</button><h1 id="agent-chat-title">模型对话</h1></div>}
      <div className="agent-header-actions">{side&&<button type="button" className={`side-toggle${sideOpen?" is-open":""}`} aria-expanded={sideOpen} aria-controls="bot-side" aria-label={sideOpen?t("收起工作区"):t("打开工作区")} title={sideOpen?t("收起工作区"):t("打开工作区")} onClick={toggleSide}><PanelIcon /><span>{t("工作区")}</span></button>}</div>
    </header>
  );
}
