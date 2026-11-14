// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useEffect, useRef, useState, type ReactNode } from "react";
import { type Bot } from "../../api";
import { ModelEffortPicker } from "../../ModelEffortPicker";
import { useLocale } from "../../i18n";
import { HistoryList } from "./HistoryList";
import { ChatHeader } from "./ChatHeader";
import { Thread } from "./Thread";
import { Composer } from "./Composer";
import { useChat } from "./ChatSessionProvider";

const SIDE_OPEN_KEY="market-evidence-agent:bot-side-open:v1";
export function ChatPage({ bot,side,onTurnSettled,onBotChanged,openSide }: { bot?: Bot | null; side?: ReactNode; onTurnSettled?: () => void; onBotChanged?: () => void; openSide?: boolean }) {
  const { t } = useLocale(), c = useChat();
  // A finished turn changes the bot's last line (and gives a new bot its conversation): tell the list.
  const wasSending=useRef(false);
  useEffect(()=>{if(c.state==="sending"){wasSending.current=true;return;}if(wasSending.current){wasSending.current=false;onTurnSettled?.();}},[c.state]); // eslint-disable-line react-hooks/exhaustive-deps
  const [historyOpen,setHistoryOpen]=useState(false);
  // A bot's right rail (工作区 / 档案) folds away so the thread can use the full width; the choice is kept.
  const [sideOpen,setSideOpen]=useState(()=>{if(openSide)return true;try{return localStorage.getItem(SIDE_OPEN_KEY)!=="0"}catch{return true}});
  const toggleSide=()=>setSideOpen(open=>{const next=!open;try{localStorage.setItem(SIDE_OPEN_KEY,next?"1":"0")}catch{/* optional preference */}return next});
  // On a narrow screen the history drawer covers the header toggle, so Esc and a tap outside close it.
  useEffect(()=>{if(!historyOpen)return;const onKey=(e:KeyboardEvent)=>{if(e.key==="Escape")setHistoryOpen(false)};window.addEventListener("keydown",onKey);return()=>window.removeEventListener("keydown",onKey)},[historyOpen]);
  const draftBox=useRef<HTMLTextAreaElement>(null);
  return <main className="workspace agent-page" aria-labelledby="agent-chat-title">
    <ChatHeader bot={bot} side={side} sideOpen={sideOpen} toggleSide={toggleSide} historyOpen={historyOpen} setHistoryOpen={setHistoryOpen} />
    <div className={`agent-layout${bot?" is-bot":""}${side&&!sideOpen?" is-side-closed":""}`}>
      <HistoryList bot={bot} historyOpen={historyOpen} setHistoryOpen={setHistoryOpen} />
      <div className="agent-main-column">
        {c.archiveView&&<div className="chat-archive-banner"><span>{t("本地归档只读查看")}</span><button className="secondary-action" onClick={c.returnLive}>{t("返回当前对话")}</button><button className="secondary-action" onClick={()=>{c.returnLive();c.clear()}}>{t("新建对话")}</button></div>}
        <div className="agent-capability"><span aria-hidden="true">✳</span><p>{t("消息和研究工具轨迹会保存到服务端；工具按权限读取资料并执行明确请求的系统任务。")}</p>{bot ? <ModelEffortPicker bot={bot} onBotChanged={onBotChanged ?? (() => undefined)} /> : <span className={`agent-connection ${c.verified ? "is-ready" : ""}`}>{c.verified ? `${t("模型")} · ${t("服务器默认模型")}` : t("登录后可用")}</span>}</div>
        <Thread draftBox={draftBox} />
        {c.status && <p className={`agent-chat-status ${c.state === "error" ? "is-error" : ""}`} role={c.state === "error" ? "alert" : "status"}>{c.status}</p>}
        <Composer bot={bot} draftBox={draftBox} />
      </div>
      {side}
    </div>
  </main>;
}
