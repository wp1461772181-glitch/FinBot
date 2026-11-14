// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { getChatMode, listAgentConversations, renameAgentConversation, archiveAgentConversation, type Bot, type ConversationSummary } from "../../api";
import { useLocale } from "../../i18n";
import { PencilIcon, ArchiveIcon } from "./icons";
import { useChat } from "./ChatSessionProvider";

function shortDate(value:string, locale:string):string {
  const date=new Date(value); if(Number.isNaN(date.valueOf())) return "";
  const today=new Date(), same=date.toDateString()===today.toDateString();
  return same?date.toLocaleTimeString(locale,{hour:"2-digit",minute:"2-digit"}):date.toLocaleDateString(locale,{month:"numeric",day:"numeric"});
}

function HistoryRow({item,current,onOpen,onRename,onArchive}:{item:ConversationSummary;current:boolean;onOpen:()=>void;onRename:(title:string)=>Promise<void>;onArchive:()=>Promise<void>}) {
  const { t, locale } = useLocale();
  const [editing,setEditing]=useState(false),[value,setValue]=useState(item.title),[error,setError]=useState(""),[saving,setSaving]=useState(false);
  const input=useRef<HTMLInputElement>(null);
  useEffect(()=>{if(editing){input.current?.focus();input.current?.select()}},[editing]);
  async function commit(){
    if(saving)return;
    const next=value.replace(/\s+/g," ").trim();
    if(next===item.title.trim()){setEditing(false);setError("");return}
    setSaving(true);setError("");
    try{await onRename(next);setEditing(false)}
    catch(e){setError(e instanceof Error?e.message:t("重命名失败，请重试"))}
    finally{setSaving(false)}
  }
  if(editing)return <div className="agent-history-row is-current"><div className="agent-history-edit">
    <input ref={input} value={value} maxLength={80} disabled={saving} aria-label={t("对话名称")} placeholder={t("对话名称（留空恢复默认）")}
      onChange={e=>setValue(e.target.value)} onBlur={()=>void commit()}
      onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();void commit()}else if(e.key==="Escape"){e.preventDefault();setValue(item.title);setError("");setEditing(false)}}} />
    <small className={error?"is-error":""}>{error||t("Enter 保存，Esc 取消")}</small>
  </div></div>;
  return <div className={`agent-history-row${current?" is-current":""}`}>
    <button type="button" className="agent-history-item" aria-current={current?"true":undefined} title={item.title} onClick={onOpen} onDoubleClick={()=>{setValue(item.title);setEditing(true)}}>
      <span className="agent-history-title">{item.title||t("新建对话")}</span>
      <span className="agent-history-time">{shortDate(item.updated_at,locale)}</span>
    </button>
    <span className="agent-history-actions">
      <button type="button" className="agent-history-rename" aria-label={t("重命名对话")} title={t("重命名")} onClick={()=>{setValue(item.title);setEditing(true)}}><span style={{display:"inline-flex",width:14,height:14}}><PencilIcon /></span></button>
      <button type="button" className="agent-history-archive" aria-label={t("归档对话")} title={t("归档（仅从列表移除，不删除内容）")} onClick={()=>{void onArchive()}}><span style={{display:"inline-flex",width:14,height:14}}><ArchiveIcon /></span></button>
    </span>
  </div>;
}

export function HistoryList({ bot, historyOpen, setHistoryOpen }: { bot?: Bot | null; historyOpen: boolean; setHistoryOpen: Dispatch<SetStateAction<boolean>> }) {
  const { t } = useLocale(), c = useChat();
  const [history,setHistory]=useState<ConversationSummary[]>([]),[historyHasMore,setHistoryHasMore]=useState(false),[historyError,setHistoryError]=useState(""),[historyLoading,setHistoryLoading]=useState(false),mode=getChatMode();
  async function refreshHistory(){setHistoryLoading(true);setHistoryError("");try{const result=await listAgentConversations();setHistory(result.conversations);setHistoryHasMore(result.hasMore)}catch(e){setHistoryError(e instanceof Error?e.message:t("历史对话暂时无法加载。"))}finally{setHistoryLoading(false)}}
  useEffect(()=>{void refreshHistory()},[c.state,mode]);
  async function loadMoreHistory(){try{const result=await listAgentConversations(history.length);setHistory(items=>[...items,...result.conversations]);setHistoryHasMore(result.hasMore)}catch(e){setHistoryError(e instanceof Error?e.message:t("历史对话暂时无法加载。"))}}
  async function openHistory(item:ConversationSummary){await c.openConversation(item.id,item.created_at);setHistoryOpen(false)}
  async function renameHistory(item:ConversationSummary,title:string){
    const saved=await renameAgentConversation(item.id,title);
    if(saved===null)await refreshHistory();   // an empty name restores the default (the first question)
    else setHistory(items=>items.map(entry=>entry.id===item.id?{...entry,title:saved,custom_title:true}:entry));
  }
  async function archiveHistory(item:ConversationSummary){
    try{await archiveAgentConversation(item.id,true)}catch(e){setHistoryError(e instanceof Error?e.message:t("归档失败，请重试"));return}
    setHistory(rows=>rows.filter(row=>row.id!==item.id));
    // 归档的是当前打开的对话时，像"新建对话"一样清空，避免继续往已归档的对话里写
    if(item.id===currentConversation)c.clear();
  }
  const currentConversation=window.sessionStorage.getItem("market-evidence-agent:chat-conversation:v1");
  return <>
      {!bot&&<>{historyOpen&&<div className="agent-history-scrim" aria-hidden="true" onClick={()=>setHistoryOpen(false)}/>}
      <aside className={`agent-history${historyOpen?" is-open":""}`} aria-label={t("历史对话")}>
        <button className="primary-action" type="button" onClick={()=>{c.clear();setHistoryOpen(false)}}>＋ {t("新建对话")}</button>
        <h2>{t("历史对话")}</h2>
        {historyLoading&&<p role="status">{t("正在读取…")}</p>}
        {historyError&&<p role="alert">{historyError} <button className="secondary-action" onClick={()=>void refreshHistory()}>{t("重试")}</button></p>}
        {!historyLoading&&!historyError&&!history.length&&<p>{t("还没有保存的对话")}</p>}
        {history.map(item=><HistoryRow key={item.id} item={item} current={Boolean(c.messages.length)&&item.id===currentConversation} onOpen={()=>void openHistory(item)} onRename={title=>renameHistory(item,title)} onArchive={()=>archiveHistory(item)} />)}
        {historyHasMore&&<button className="secondary-action" onClick={()=>void loadMoreHistory()}>{t("加载更多")}</button>}
      </aside></>}
  </>;
}
