import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { getChatMode, listAgentConversations, renameAgentConversation, archiveAgentConversation, type Bot, type ConversationSummary } from "../../api";
import { useLocale } from "../../i18n";
import { Archive, Pencil, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SkeletonRows, DelayedSkeleton } from "@/components/state/Skeleton";
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
    catch(e){setError(e instanceof Error?t(e.message):t("重命名失败，请重试"))}
    finally{setSaving(false)}
  }
  if(editing)return <div className="rounded-md bg-accent p-2"><div className="flex flex-col gap-1">
    <input ref={input} className="h-9 w-full rounded-sm border border-line-strong bg-surface px-2 text-body text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring" value={value} maxLength={80} disabled={saving} aria-label={t("对话名称")} placeholder={t("对话名称（留空恢复默认）")}
      onChange={e=>setValue(e.target.value)} onBlur={()=>void commit()}
      onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();void commit()}else if(e.key==="Escape"){e.preventDefault();setValue(item.title);setError("");setEditing(false)}}} />
    <small className={`text-caption ${error?"text-danger":"text-muted-foreground"}`}>{error||t("Enter 保存，Esc 取消")}</small>
  </div></div>;
  const rowButton="inline-flex size-8 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-background hover:text-ink focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-3.5";
  return <div data-testid="history-row" className={`group/row flex items-center gap-1 rounded-md ${current?"bg-accent":"hover:bg-accent/60"}`}>
    <button type="button" className="flex min-w-0 flex-1 flex-col gap-0.5 rounded-md px-3 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-current={current?"true":undefined} title={item.title} onClick={onOpen} onDoubleClick={()=>{setValue(item.title);setEditing(true)}}>
      <span className="truncate text-body text-ink">{item.title||t("新建对话")}</span>
      <span className="text-caption text-muted-foreground">{shortDate(item.updated_at,locale)}</span>
    </button>
    <span className="flex shrink-0 pr-1 opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100">
      <button type="button" className={rowButton} aria-label={t("重命名对话")} title={t("重命名")} onClick={()=>{setValue(item.title);setEditing(true)}}><Pencil aria-hidden="true" /></button>
      <button type="button" className={rowButton} aria-label={t("归档对话")} title={t("归档（仅从列表移除，不删除内容）")} onClick={()=>{void onArchive()}}><Archive aria-hidden="true" /></button>
    </span>
  </div>;
}

export function HistoryList({ bot, historyOpen, setHistoryOpen }: { bot?: Bot | null; historyOpen: boolean; setHistoryOpen: Dispatch<SetStateAction<boolean>> }) {
  const { t } = useLocale(), c = useChat();
  const [history,setHistory]=useState<ConversationSummary[]>([]),[historyHasMore,setHistoryHasMore]=useState(false),[historyError,setHistoryError]=useState(""),[historyLoading,setHistoryLoading]=useState(false),mode=getChatMode();
  async function refreshHistory(){setHistoryLoading(true);setHistoryError("");try{const result=await listAgentConversations();setHistory(result.conversations);setHistoryHasMore(result.hasMore)}catch(e){setHistoryError(e instanceof Error?t(e.message):t("历史对话暂时无法加载。"))}finally{setHistoryLoading(false)}}
  useEffect(()=>{void refreshHistory()},[c.state,mode]);
  async function loadMoreHistory(){try{const result=await listAgentConversations(history.length);setHistory(items=>[...items,...result.conversations]);setHistoryHasMore(result.hasMore)}catch(e){setHistoryError(e instanceof Error?t(e.message):t("历史对话暂时无法加载。"))}}
  async function openHistory(item:ConversationSummary){await c.openConversation(item.id,item.created_at);setHistoryOpen(false)}
  async function renameHistory(item:ConversationSummary,title:string){
    const saved=await renameAgentConversation(item.id,title);
    if(saved===null)await refreshHistory();   // an empty name restores the default (the first question)
    else setHistory(items=>items.map(entry=>entry.id===item.id?{...entry,title:saved,custom_title:true}:entry));
  }
  async function archiveHistory(item:ConversationSummary){
    try{await archiveAgentConversation(item.id,true)}catch(e){setHistoryError(e instanceof Error?t(e.message):t("归档失败，请重试"));return}
    setHistory(rows=>rows.filter(row=>row.id!==item.id));
    // 归档的是当前打开的对话时，像"新建对话"一样清空，避免继续往已归档的对话里写
    if(item.id===currentConversation)c.clear();
  }
  const currentConversation=window.sessionStorage.getItem("market-evidence-agent:chat-conversation:v1");
  return <>
      {!bot&&<>{historyOpen&&<div className="fixed inset-0 z-overlay bg-black/30 lg:hidden" aria-hidden="true" onClick={()=>setHistoryOpen(false)}/>}
      <aside data-testid="history-list" data-open={historyOpen} aria-label={t("历史对话")}
        className="z-overlay flex min-h-0 flex-col gap-1 overflow-y-auto border-r border-line bg-background p-3 max-lg:fixed max-lg:inset-y-0 max-lg:left-0 max-lg:w-72 max-lg:shadow-modal max-lg:data-[open=false]:hidden lg:static lg:z-auto">
        <Button type="button" variant="outline" className="justify-start" onClick={()=>{c.clear();setHistoryOpen(false)}}><Plus aria-hidden="true" />{t("新建对话")}</Button>
        <h2 className="px-2 pb-1 pt-3 text-caption font-medium text-muted-foreground">{t("历史对话")}</h2>
        {historyLoading&&!history.length&&<DelayedSkeleton active><SkeletonRows rows={4} /></DelayedSkeleton>}
        {historyError&&<p role="alert" className="flex items-center gap-2 px-2 text-small text-danger">{historyError} <Button type="button" variant="ghost" size="sm" onClick={()=>void refreshHistory()}>{t("重试")}</Button></p>}
        {!historyLoading&&!historyError&&!history.length&&<p className="px-2 text-small text-muted-foreground">{t("还没有保存的对话")}</p>}
        {history.map(item=><HistoryRow key={item.id} item={item} current={Boolean(c.messages.length)&&item.id===currentConversation} onOpen={()=>void openHistory(item)} onRename={title=>renameHistory(item,title)} onArchive={()=>archiveHistory(item)} />)}
        {historyHasMore&&<Button type="button" variant="ghost" size="sm" onClick={()=>void loadMoreHistory()}>{t("加载更多")}</Button>}
      </aside></>}
  </>;
}
