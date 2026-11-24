// The chat session: the state machine behind the thread (SSE turns, one line per bot, cross-tab sync, archive).  No markup here.
import { dispatchAgentAction } from "../../agent-client-actions.mjs";
import { createContext, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { agentChatStream, restoreAgentChat, compactConversation, cancelAgentTurn, clearAgentConversation, selectAgentConversation, type AgentChatMessage, type AgentChatEvent } from "../../api/conversations";
import { ApiError, getChatMode } from "../../api/base";
import { type Bot } from "../../api/bots";
import { normalizeUnverified } from "../../chat-unverified.mjs";
import { useLocale } from "../../i18n";
import { chatContext } from "../../agentChatLifecycle.js";
import { createLineStore, lineKey, loadDraft, saveDraft } from "../../chat-lines.mjs";
import { planTailSync, pollDelay } from "../../chat-sync.mjs";
import { arrivalSplit, backgroundExpired, completeTurnsOnly, dropDetached, loadDetached, markDetachedGone, resumePlan, restoredBeforeSend, saveDetached, streamBreak, type Background } from "../../chat-detached.mjs";
import { parseCompactCommand, type CompactionNotice } from "../../context-usage.mjs";
import { restoreConversationAfterPersistence, restoreConversationSafely } from "../../chat-session.mjs";
import { normalizeClarification, selectedClarification, selectedOptions, manualClarification } from "../../chat-clarification.mjs";
import { cancelRunning, upsertNode, type FlowNode } from "../../turn-flow.mjs";
import { addToWatchlist, queueAddTicker, watchlistSnapshot } from "../../watchlist-bridge.mjs";
import { createArchive, createSerializedWriter, isPickerCancelled, mergeConversation, serializeArchive, validateArchive, writeAtomically, type ArchiveConversation, type ChatArchive } from "../../chat-archive.mjs";
import { errorReason } from "@/components/state/error-message";
import { newTurnIds, retryPlan } from "../../chat-states.mjs";
import { KERNEL_TOOLS } from "../../turn-progress.mjs";
import type { LiveMessage, SentRequest } from "./live-message";

type State = "idle" | "testing" | "ready" | "sending" | "restoring" | "error";

type FileHandle = { name: string; getFile: () => Promise<File>; createWritable: () => Promise<{ write: (value: string) => Promise<void>; close: () => Promise<void> }> };
type ChatSession = { conversationId:string|null; verified: boolean; state: State; status: string; restoring:boolean; messages: AgentChatMessage[]; historyHasMore:boolean; loadingEarlier:boolean; loadEarlier:()=>Promise<void>; draft: string; setDraft: (v: string) => void; send: (e: FormEvent) => Promise<void>; choose:(value:string,requestId:string)=>Promise<void>; chooseOptions:(values:string[],requestId:string)=>Promise<void>; replyToCard:(value:string,requestId:string)=>Promise<void>; cancel: () => void; clear: () => void; openConversation:(id:string,created?:string)=>Promise<void>; archive: ChatArchive | null; archiveView: ArchiveConversation | null; fileName: string; archiveStatus: string; connectFile: () => Promise<void>; disconnectFile: () => void; exportArchive: () => void; importArchive: (file: File) => Promise<void>; selectArchive: (id:string) => void; returnLive: () => void; bot: Bot | null; selectBot: (bot: Bot | null) => Promise<void>; lineStatus: { running: string[]; unseen: string[]; waiting: string[] }; freshExternal: boolean; ackExternal: () => void; externalTurns: string[]; retry: () => Promise<void>; notices: CompactionNotice[]; compactNow: (focus:string)=>Promise<void>; background: Background | null; cancelBackground: () => Promise<void>; awayTurns: string[] };
const Context = createContext<ChatSession | null>(null);

export function AgentChatProviderRoot({ children }: { children: ReactNode }) {
  const { t } = useLocale();
  // Models come only from the server catalog (UX batch 3): the owner's turns name a bot or the catalog default,
  // never a key.  A guest has no catalog, so a guest cannot send until they log in.
  const verified = getChatMode() === "personal", [state, setState] = useState<State>("idle"), [status, setStatus] = useState(""), [messages, setMessages] = useState<AgentChatMessage[]>([]), [draft, setDraftState] = useState(() => loadDraft("local")), [conversationId, setConversationId] = useState<string | null>(null);
  const [historyHasMore,setHistoryHasMore]=useState(false),[historyBefore,setHistoryBefore]=useState<number|null>(null),[loadingEarlier,setLoadingEarlier]=useState(false);
  const conversationIdRef=useRef<string|null>(null); conversationIdRef.current=conversationId;
  // The bot whose line is open.  Its turns send only bot_id: the server takes the model and key from its catalog.
  const [bot,setBot]=useState<Bot|null>(null), botRef=useRef<Bot|null>(null);
  const earlierController=useRef<AbortController|null>(null),loadingEarlierRef=useRef(false);
  const [restoring,setRestoring]=useState(false);
  const [archive,setArchive]=useState<ChatArchive|null>(null),[archiveView,setArchiveView]=useState<ArchiveConversation|null>(null),[fileName,setFileName]=useState(""),[archiveStatus,setArchiveStatus]=useState(""),[importedReadOnly,setImportedReadOnly]=useState(false);
  const connectedArchive=useRef<ChatArchive|null>(null), archiveRef=useRef<ChatArchive|null>(null), createdAt=useRef(new Date().toISOString()), epoch=useRef(0);
  const handle=useRef<FileHandle|null>(null), localId=useRef(readLocalConversationId()), writer=useRef(createSerializedWriter(async (target:FileHandle,data:string)=>{if(!target)throw new Error("未连接归档文件");await writeAtomically(target,data);}));
  // One state per chat line (a bot's line, or the legacy "local" one): switching the viewed line never aborts another line's request.
  const lines = useRef(createLineStore<AgentChatMessage>()), lineRef = useRef("local"), [, bump] = useState(0);
  lines.current.setActive(lineRef.current);
  const lifecycle = { get current() { return lines.current.get(lineRef.current).lifecycle; } };
  // FP13-c: the turn a line left running on the server (the banner), the turns this page did not watch finish (by conversation), and per-turn send bookkeeping.
  const [background,setBackground]=useState<Background|null>(null), [awayByConv,setAwayByConv]=useState<Record<string,string[]>>({});
  const liveTurns = useRef(new Map<string, {detachable: boolean; turnId?: string; conversationId: string | null}>()), presync = useRef(false);
  const localStore = () => { try { return window.localStorage; } catch { return undefined; } };
  // Write a line's state; only the viewed line mirrors it into the React state, so a background answer cannot touch the page.
  function apply(line:string, patch:{messages?:AgentChatMessage[];state?:State;status?:string;conversationId?:string|null;historyHasMore?:boolean;historyBefore?:number|null;restoring?:boolean;draft?:string;loaded?:boolean;background?:Background|null}) {
    lines.current.update(line, patch);
    if (lineRef.current === line) { if (patch.messages !== undefined) { setMessages(patch.messages); latestMessages.current = patch.messages; } if (patch.state !== undefined) setState(patch.state); if (patch.status !== undefined) setStatus(patch.status); if (patch.conversationId !== undefined) setConversationId(patch.conversationId); if (patch.historyHasMore !== undefined) setHistoryHasMore(patch.historyHasMore); if (patch.historyBefore !== undefined) setHistoryBefore(patch.historyBefore); if (patch.restoring !== undefined) setRestoring(patch.restoring); if (patch.draft !== undefined) setDraftState(patch.draft); if (patch.background !== undefined) setBackground(patch.background); }
    bump(n => n + 1);
  }
  const setDraft = (text:string) => { setDraftState(text); lines.current.update(lineRef.current, { draft: text }); saveDraft(lineRef.current, text); };
  useEffect(() => () => { for (const [, s] of lines.current.all()) s.lifecycle.invalidate(); }, []);
  useEffect(() => { const line="local", lc=lines.current.get(line).lifecycle, controller=new AbortController(), id=lc.begin(controller); apply(line,{restoring:true,state:"restoring"}); void restoreConversationSafely(lc,id,controller.signal,signal=>restoreAgentChat(undefined,signal),saved=>{if(!saved.conversationId)clearAgentConversation();else{localId.current=saved.conversationId;createdAt.current=saved.createdAt??new Date().toISOString();try{window.localStorage.setItem(`market-evidence-agent:local-chat-id:${getChatMode()}:v1`,localId.current)}catch{}}apply(line,{conversationId:saved.conversationId,messages:saved.messages.filter(m=>m.role==="user"||m.role==="assistant"),historyHasMore:saved.hasMore,historyBefore:saved.nextBefore,state:"idle",loaded:true});if(saved.conversationId)resumeLine(line,saved.conversationId,saved.messages.filter(m=>m.role==="user"||m.role==="assistant"))}).catch(() => { if (lc.isCurrent(id)) apply(line,{status:t("历史记录暂时无法加载；可稍后重试。"),state:"idle"}); }).finally(()=>{if(lc.isCurrent(id))apply(line,{restoring:false})}); return () => { controller.abort(); earlierController.current?.abort(); lc.finish(id); }; }, []);
  const latestMessages=useRef(messages);latestMessages.current=messages;
  // Turns pulled in from outside this tab since the user last interacted: the main avatar shows its notification until then.
  const [freshExternal,setFreshExternal]=useState(false);
  // The turns that came in from outside since the line was opened (the thread marks where each starts).
  const [externalTurns,setExternalTurns]=useState<string[]>([]);
  useEffect(()=>{setFreshExternal(false);setExternalTurns([])},[conversationId]);
  const lastRequests=useRef(new Map<string,SentRequest>());
  // 「已压缩 N 轮」 lines of this conversation (the server writes one per summary version; the summary opens from it).
  const [notices,setNotices]=useState<CompactionNotice[]>([]);
  const refreshNotices=(id:string|null)=>{ if(!id){setNotices([]);return Promise.resolve();} return restoreAgentChat(id,undefined,false,null,1).then(page=>{ if(conversationIdRef.current===id) setNotices(page.compactions??[]); }).catch(()=>{}); };
  useEffect(()=>{ void refreshNotices(conversationId); },[conversationId]);
  // An automatic compression runs in the background after an answer; look again shortly after each one.
  useEffect(()=>{ if(state==="sending"||!conversationId) return; const id=conversationId, timers=[setTimeout(()=>void refreshNotices(id),4000),setTimeout(()=>void refreshNotices(id),25000)]; return ()=>timers.forEach(clearTimeout); },[state,conversationId,messages.length]);
  async function compactNow(focus:string) {
    const id=conversationIdRef.current, line=lineRef.current;
    if(!id){ setStatus(t("还没有对话可压缩。")); return; }
    if(state==="sending"||state==="testing"){ setStatus(t("回答完成后再压缩。")); return; }
    setStatus(t("正在压缩…"));
    try { const result=await compactConversation(id,botRef.current?.id??null,focus); setStatus(t(result.message)); await refreshNotices(id); }
    catch(error) { setStatus(t(error instanceof Error ? error.message : "压缩没有成功，稍后再试。")); }
    finally { if(lineRef.current===line) apply(line,{draft:""}); }
  }
  // Live refresh: while a conversation is open, pull in turns written from outside this tab (Telegram, reminders, pushes).
  // Polls the newest turns every few seconds (slowly while the tab is hidden) and appends only unseen turn ids; never touches a line that is
  // answering or restoring, and never the draft (see chat-sync.mjs).
  useEffect(() => {
    if (!conversationId || archiveView || importedReadOnly) return;
    const line = lineRef.current, target = conversationId;
    let timer = 0, failures = 0, controller: AbortController | null = null, stopped = false;
    const schedule = () => { if (!stopped) timer = window.setTimeout(() => void poll(), pollDelay({ hidden: document.visibilityState === "hidden", failures })); };
    async function poll() {
      if (stopped) return;
      if (document.visibilityState === "hidden") { schedule(); return; }
      const current = lines.current.get(line);
      if (lineRef.current !== line || current.restoring || current.state === "sending" || current.state === "testing" || current.state === "restoring") { schedule(); return; }
      controller = new AbortController();
      try {
        const page = await restoreAgentChat(target, controller.signal, true, null, 6);
        if (stopped || controller.signal.aborted || lineRef.current !== line || conversationIdRef.current !== target) return;
        mergeTail(line, target, page);
        failures = 0;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        failures += 1;
      }
      schedule();
    }
    const onVisible = () => { if (document.visibilityState === "visible" && !stopped) { window.clearTimeout(timer); controller?.abort(); void poll(); } };
    document.addEventListener("visibilitychange", onVisible);
    schedule();
    return () => { stopped = true; window.clearTimeout(timer); controller?.abort(); document.removeEventListener("visibilitychange", onVisible); };
  }, [conversationId, archiveView, importedReadOnly]);
  useEffect(()=>{if(!handle.current||(state!=="ready"&&state!=="error")||archiveView||importedReadOnly||messages.length===0)return;const timer=window.setTimeout(()=>void persistConversation(messages),700);return()=>window.clearTimeout(timer);},[messages,state,archiveView,importedReadOnly]);
  async function persistConversation(items:AgentChatMessage[]){const target=handle.current;if(!target||items.length===0)return;try{const now=new Date().toISOString(),conversation:ArchiveConversation={id:localId.current,created_at:createdAt.current,updated_at:now,messages:archiveMessages(items)};const merged=mergeConversation(connectedArchive.current??createArchive(),conversation);connectedArchive.current=merged;const version=epoch.current;await writer.current(target,serializeArchive(merged));if(version===epoch.current&&!importedReadOnly){archiveRef.current=merged;setArchive(merged);setArchiveStatus(`${t("上次成功保存时间")}: ${new Date().toLocaleTimeString()}`);}}catch(e){setArchiveStatus(`${t("自动保存失败")}: ${e instanceof Error?e.message:""}`);}}
  async function connectFile(){try{const w=window as Window&{showSaveFilePicker?: (options:unknown)=>Promise<FileHandle>};if(!w.showSaveFilePicker){setArchiveStatus(t("当前浏览器不支持自动写入文件；请使用导出和导入。"));return;}const target=await w.showSaveFilePicker({suggestedName:"market-evidence-chat.json",types:[{description:"JSON chat archive",accept:{"application/json":[".json"]}}]});const file=await target.getFile();if(file.size>5_000_000)throw Error("归档文件超过 5 MB 限制");const loaded=file.size?validateArchive(await file.text()):createArchive();epoch.current++;handle.current=target;connectedArchive.current=loaded;archiveRef.current=loaded;setImportedReadOnly(false);setArchiveView(null);setArchive(loaded);setFileName(target.name);setArchiveStatus(t("本地归档已连接"));if(latestMessages.current.length)await persistConversation(latestMessages.current);}catch(e){if(isPickerCancelled(e))return;setArchiveStatus(`${t("无法连接归档文件")}: ${e instanceof Error?e.message:""}`);}}
  function disconnectFile(){epoch.current++;handle.current=null;connectedArchive.current=null;setFileName("");setArchiveStatus(t("已断开本地归档"));}
  function exportArchive(){const now=new Date().toISOString();let data=archive??createArchive();if(!archiveView&&messages.length){data=mergeConversation(data,{id:localId.current,created_at:now,updated_at:now,messages:archiveMessages(messages)});}const blob=new Blob([serializeArchive(data)],{type:"application/json;charset=utf-8"});const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="market-evidence-chat.json";a.click();URL.revokeObjectURL(url);}
  async function importArchive(file:File){try{if(file.size>5_000_000)throw new Error("归档文件超过 5 MB 限制");const loaded=validateArchive(await file.text());epoch.current++;setImportedReadOnly(true);setArchive(loaded);setArchiveView(loaded.conversations.at(-1)??null);setArchiveStatus(t("归档已打开，只读查看"));}catch(e){setArchiveStatus(e instanceof Error?t(e.message):t("归档文件无效"));}}
  function returnLive(){setArchiveView(null);if(importedReadOnly){setImportedReadOnly(false);setArchive(archiveRef.current);}setArchiveStatus(t("已返回当前对话"));}
  function selectArchive(id:string){const item=archive?.conversations.find(x=>x.id===id);if(item)setArchiveView(item);}
  const cancelledMessages = (items: AgentChatMessage[]): AgentChatMessage[] => {
    const last = items.at(-1);
    if (last?.role === "assistant") return [...items.slice(0, -1), { ...last, status: "cancelled", tool_trace: last.tool_trace?.map(x => x.status === "running" ? { ...x, status: "cancelled" } : x), trace: last.trace ? cancelRunning(last.trace, "cancelled") : last.trace }];
    if (last?.role === "user") return [...items, { role: "assistant", content: "", status: "cancelled" }];
    return items;
  };
  function translate(s: string) { return t(s); }
  async function send(e: FormEvent) {
    e.preventDefault();
    const command=parseCompactCommand(draft.trim());
    if (command.compact) { saveDraft(lineRef.current,""); await compactNow(command.focus); return; }
    await sendContent(draft.trim());
  }
  async function choose(value:string,requestId:string) {
    const card=messages.at(-1)?.clarification;
    if (!card || card.request_id!==requestId) return;
    const selection=selectedClarification(card,value);
    const queued=queueAddTicker(value); if(queued) addToWatchlist(queued);
    await sendContent(selection.message,selection.pendingRequestId,card.choices.find(choice=>choice.value===value)?.label);
  }
  async function chooseOptions(values:string[],requestId:string) {
    const card=messages.at(-1)?.clarification;
    if (!card || card.request_id!==requestId) return;
    const selection=selectedOptions(card,values);
    await sendContent(selection.message,selection.pendingRequestId,selection.label);
  }
  // 重试: the failed turn comes off the end of the line and the question it answered goes out again, as the same request.
  async function retry() {
    const plan = retryPlan(latestMessages.current, lastRequests.current.get(lineRef.current));
    if (!plan || archiveView) return;
    await sendContent(plan.content, plan.pendingRequestId, plan.label, plan.base);
  }
  async function replyToCard(value:string,requestId:string) {
    const card=messages.at(-1)?.clarification;
    if (!card || card.request_id!==requestId || archiveView) return;
    const reply=manualClarification(card,value);
    await sendContent(reply.message,reply.pendingRequestId);
  }
  async function sendContent(content:string,pendingRequestId?:string,label?:string,base?:AgentChatMessage[]) {
    if (!(verified||botRef.current) || loadingEarlierRef.current || !content || state === "sending" || state === "testing") return;
    // FP13-c: a line with a turn still running on the server first pulls in what has finished (one sync at a time; a second send returns here).
    const syncLine = lineRef.current;
    if (lines.current.get(syncLine).background) { if (presync.current) return; presync.current = true; try { await syncBeforeSend(syncLine); } finally { presync.current = false; } }
    let context: AgentChatMessage[]; const history = base ?? latestMessages.current; try { context = chatContext(history, { role: "user", content }); } catch (error) { setStatus(t(error instanceof Error ? error.message : "消息过长，请缩短后重试。")); return; }
    const line = lineRef.current, lc = lines.current.get(line).lifecycle;
    const next = [...history, { role: "user" as const, content: label||content }]; lastRequests.current.set(line, { content, pendingRequestId, label }); saveDraft(line, ""); const before = latestMessages.current; apply(line, { messages: next, draft: "", state: "sending", status: "" }); liveTurns.current.set(line, { detachable: false, conversationId: lines.current.get(line).conversationId }); const turnBot = botRef.current, tested = turnBot ? { bot_id: turnBot.id } : { catalog_model: "" }, controller = new AbortController(), id = lc.begin(controller);
    let detachable = false, sawTerminal = false; let localQueue = ""; let accumulated = ""; let turnId: string|undefined; let citations: NonNullable<AgentChatMessage["citations"]> = []; let citationProtocol: string|undefined; let citationNodes: NonNullable<AgentChatMessage["citation_nodes"]> = []; let clarification:AgentChatMessage["clarification"]; let cardAt:number|undefined; let terminalStatus="complete"; let reusedSources=false; let unverified: ReturnType<typeof normalizeUnverified> = []; const tools: NonNullable<AgentChatMessage["tool_trace"]> = []; let trace: FlowNode[] = []; let thinkingMs: number|undefined; const narration: string[] = []; let checklist: NonNullable<AgentChatMessage["checklist"]>|undefined; let tier: string|undefined; const startedAt = Date.now(); const liveFields = (): Partial<LiveMessage> => (cardAt ? { card_at: cardAt } : {});
    try {
      await agentChatStream(tested, content, turnBot ? null : conversationId, controller.signal, (event: AgentChatEvent) => {
        if (!lc.isCurrent(id)) return false;
        if (event.event === "conversation" && typeof event.data.conversation_id === "string") {if(typeof event.data.turn_id==="string")turnId=event.data.turn_id;const cid=event.data.conversation_id;if(lineRef.current===line&&cid!==conversationId){const created=new Date().toISOString();localId.current=cid;createdAt.current=created;selectAgentConversation(cid,created)}apply(line,{conversationId:cid});}
        if (event.event === "conversation" && typeof event.data.conversation_id === "string") { const cid=String(event.data.conversation_id); apply(line,{background:null}); const live=liveTurns.current.get(line); if(live){live.turnId=turnId;live.conversationId=cid;} if(detachable&&turnId) saveDetached(localStore(),cid,{turnId,question:(label||content).slice(0,4000),at:startedAt}); }
        if (event.event === "client_action") {
          const applied=dispatchAgentAction(event.data, window);
          if (applied && event.data.action === "show_queue") localQueue=`\n\n${t("研究队列")}: ${(watchlistSnapshot() ?? []).join(", ") || "—"}`;
        }
        if (event.event === "status") { const labels: Record<string,string>={resolving_reference:"正在理解问题…",recognizing_intent:"正在识别任务…",planning_tasks:"正在规划查询…",expanding_query:"正在扩展检索词…",expansion_degraded:"检索词扩展不可用，继续原查询…",reusing_sources:"正在复用已核实来源…",writing_answer:"正在组织回答…"}; apply(line,{status:t(labels[String(event.data.status)]??"正在选择研究工具…")}); }
        if (event.event === "narration" && typeof event.data.text === "string") narration.push(event.data.text);
        if (event.event === "checklist" && Array.isArray(event.data.items)) checklist = event.data.items as NonNullable<AgentChatMessage["checklist"]>;
        if (event.event === "tier" && typeof event.data.tier === "string") tier = event.data.tier;
        if (event.event === "tool_start" && !KERNEL_TOOLS.includes(String(event.data.name))) { tools.push({ call_id: String(event.data.call_id), name: String(event.data.name), arguments: event.data.arguments, status: "running" }); apply(line,{status:t("正在查询研究数据…")}); }
        if (event.event === "tool_result") { const item = tools.find(x => x.call_id === event.data.call_id); if (item) { item.result = event.data.result; const result = event.data.result as { ok?: boolean; data?: unknown };
          item.status = !result?.ok ? "failed" : Array.isArray(result.data) && result.data.length === 0 ? "not_found" : "complete"; } }
        if (event.event === "citations" && Array.isArray(event.data.items)) citations = event.data.items as NonNullable<AgentChatMessage["citations"]>;
        if (event.event === "unverified_lines") unverified = normalizeUnverified(event.data.items);
        if (event.event === "clarification") { clarification=normalizeClarification(event.data)??undefined; cardAt=clarification?Date.now():undefined; }
        if (event.event === "trace") trace = upsertNode(trace, event.data);
        if (event.event === "done") {citationProtocol=event.data.citation_protocol==="v2"?"v2":undefined;citationNodes=Array.isArray(event.data.citation_nodes)?event.data.citation_nodes as NonNullable<AgentChatMessage["citation_nodes"]>:citationNodes;terminalStatus=String(event.data.status??"complete");reusedSources=(event.data.audit as {reused_sources?:boolean}|undefined)?.reused_sources===true;const thinking=Number(event.data.thinking_ms);if(Number.isFinite(thinking))thinkingMs=thinking;}
        if (event.event === "done" || event.event === "error") { sawTerminal = true; const cid = liveTurns.current.get(line)?.conversationId; if (cid) dropDetached(localStore(), cid); }
        if (event.event === "delta" && typeof event.data.text === "string") accumulated += event.data.text;
        if (event.event === "answer_reset") accumulated = "";
        if (event.event === "error") throw new Error(String(event.data.code ?? "chat_failed"));
        apply(line,{messages:[...next, { role: "assistant", content: accumulated + localQueue, turn_id:turnId, tool_trace: [...tools], citations, citation_protocol: citationProtocol, citation_nodes: citationNodes, unverified_lines: unverified, clarification, trace, thinking_ms: thinkingMs, started_at: startedAt, ...(narration.length ? { narration: [...narration] } : {}), ...(checklist ? { checklist } : {}), ...(tier ? { tier } : {}), status:terminalStatus, reused_sources:reusedSources, ...liveFields() }]});
        return true;
      },pendingRequestId,label,(note)=>{ if (note === "detached") { detachable = true; const live=liveTurns.current.get(line); if(live) live.detachable=true; } });
      if (!lc.isCurrent(id)) return; apply(line,{messages:[...next, { role: "assistant", content: accumulated + localQueue, turn_id:turnId, tool_trace: [...tools], citations, citation_protocol: citationProtocol, citation_nodes: citationNodes, unverified_lines: unverified, clarification, trace, thinking_ms: thinkingMs, started_at: startedAt, ...(narration.length ? { narration: [...narration] } : {}), ...(checklist ? { checklist } : {}), ...(tier ? { tier } : {}), status:terminalStatus, reused_sources:reusedSources, ...liveFields() }],status:"",state:"ready"});
    }
    catch (error) { if (!lc.isCurrent(id)) return;
      // FP13-c (§3.6): the server refused the send as busy, before anything was written.  The list goes back to what it was, the text back to the box.
      if (error instanceof ApiError && error.status === 409 && error.message === "conversation_busy") {
        const priorBackground = lines.current.get(line).background, known = lines.current.get(line).conversationId;
        apply(line,{messages: before, state:"ready", status:""});
        if (!pendingRequestId && !label && !base) { apply(line,{draft:content}); saveDraft(line, content); }
        apply(line,{background:{conversationId: known, turnId: priorBackground?.turnId ?? null, reason:"busy", at: Date.now()}});
        return;
      }
      // FP13-c (§3.2): a broken stream of a detached turn is a background turn, or an ended one; anything else falls through unchanged.
      const cid = liveTurns.current.get(line)?.conversationId ?? lines.current.get(line).conversationId, turnNow = liveTurns.current.get(line)?.turnId ?? null;
      const kind = streamBreak({ aborted: error instanceof DOMException && error.name === "AbortError", detachable, sawTerminal, closed: error instanceof ApiError && error.message === "provider_incomplete_stream" });
      if (kind === "detached") { apply(line,{messages: next, state:"ready", status:"", background:{conversationId: cid, turnId: turnNow, reason:"dropped", at: Date.now()}}); return; }
      if (kind === "ended") { if (cid) markDetachedGone(localStore(), cid); apply(line,{messages: next, state:"ready", status: t("这一轮在服务器上结束了，但这里没有收到回答；已保存的结果会自动出现在对话里。")}); return; }
      const stopped=error instanceof DOMException && error.name==="AbortError"; const failure={ code:error instanceof Error?error.message:"", network:error instanceof TypeError, message:error instanceof Error ? errorReason(error, translate) : translate("发送失败，请重试") }; const stoppedTools=tools.map(x => x.status === "running" ? { ...x, status: "cancelled" } : x); apply(line,{messages:[...next, { role:"assistant",content:accumulated,status:stopped?"cancelled":"failed",tool_trace:stoppedTools,trace:cancelRunning(trace,stopped?"cancelled":"failed"),thinking_ms:thinkingMs??Date.now()-startedAt, ...(narration.length ? { narration: [...narration] } : {}), ...(checklist ? { checklist } : {}), ...(tier ? { tier } : {}), ...(stopped?{}:{ failure }) }],state:stopped?"ready":"error",status:stopped?"":failure.message}); }
    finally { lc.finish(id); }
  }
  const cancel = () => { const line = lineRef.current, wasSending = state === "sending"; const live = liveTurns.current.get(line), liveCid = live?.conversationId ?? lines.current.get(line).conversationId; if (wasSending && live?.detachable && liveCid) void stopDetached(line, liveCid, live.turnId); lifecycle.current.invalidate(); apply(line, { ...(wasSending ? { messages: cancelledMessages(latestMessages.current) } : {}), restoring: false, state: verified ? "ready" : "idle", status: "" }); };
  async function openConversation(id:string, created?:string){
    earlierController.current?.abort();loadingEarlierRef.current=false;setLoadingEarlier(false);
    const previous=latestMessages.current;let lastUser=-1;for(let i=previous.length-1;i>=0;i--)if(previous[i].role==="user"){lastUser=i;break;}const completed=state==="sending"?previous.slice(0,Math.max(0,lastUser)):previous;
    const line=lineRef.current, lc=lines.current.get(line).lifecycle, controller=new AbortController(), token=lc.begin(controller);apply(line,{restoring:true,state:"restoring",status:""});
    try{await restoreConversationAfterPersistence(lc,token,controller.signal,()=>handle.current&&completed.length?persistConversation(completed):Promise.resolve(),signal=>restoreAgentChat(id,signal,true),saved=>{const restoredId=saved.conversationId??id,chosenCreatedAt=created??saved.createdAt??new Date().toISOString();const display=saved.messages.filter(m=>m.role==="user"||m.role==="assistant");if(lineRef.current===line){selectAgentConversation(restoredId,chosenCreatedAt);localId.current=restoredId;createdAt.current=chosenCreatedAt;try{window.localStorage.setItem(`market-evidence-agent:local-chat-id:${getChatMode()}:v1`,restoredId)}catch{}setArchiveView(null);setImportedReadOnly(false);}apply(line,{conversationId:restoredId,messages:display,historyHasMore:saved.hasMore,historyBefore:saved.nextBefore,state:verified?"ready":"idle",loaded:true});resumeLine(line,restoredId,display)})}
    catch(error){if(lc.isCurrent(token)&&!(error instanceof DOMException&&error.name==="AbortError")){apply(line,{status:t("无法恢复服务端聊天记录。"),state:verified?"ready":"idle"});}}
    finally{if(lc.isCurrent(token)){lc.finish(token);apply(line,{restoring:false})}}
  }
  async function loadEarlier(){
    if(!conversationId||!historyHasMore||historyBefore===null||loadingEarlierRef.current||restoring||state==="sending"||state==="testing"||archiveView||importedReadOnly)return;
    const line=lineRef.current,target=conversationId,cursor=historyBefore;
    earlierController.current?.abort();
    const controller=new AbortController();earlierController.current=controller;
    loadingEarlierRef.current=true;setLoadingEarlier(true);
    try{
      const page=await restoreAgentChat(target,controller.signal,true,cursor,20);
      if(controller.signal.aborted||lineRef.current!==line||conversationIdRef.current!==target)return;
      const older=page.messages.filter(m=>m.role==="user"||m.role==="assistant");
      apply(line,{...(older.length?{messages:[...older,...lines.current.get(line).messages]}:{}),historyBefore:page.nextBefore,historyHasMore:page.hasMore});
    }catch(error){
      if(!(error instanceof DOMException&&error.name==="AbortError")&&conversationIdRef.current===target)setStatus(t("更早的聊天记录暂时无法加载。"));
    }finally{
      if(earlierController.current===controller){earlierController.current=null;loadingEarlierRef.current=false;setLoadingEarlier(false);}
    }
  }
  const clearLine = (keepDraft:boolean) => { const line=lineRef.current; earlierController.current?.abort();loadingEarlierRef.current=false;setLoadingEarlier(false); const previous=latestMessages.current;let lastUser=-1;for(let i=previous.length-1;i>=0;i--)if(previous[i].role==="user"){lastUser=i;break;}const completed=state==="sending"?previous.slice(0,Math.max(0,lastUser)):previous;if(handle.current&&completed.length)void persistConversation(completed); lifecycle.current.invalidate();setArchiveView(null);if(importedReadOnly){setImportedReadOnly(false);setArchive(archiveRef.current);}clearAgentConversation(); if(!keepDraft)saveDraft(line,""); localId.current=crypto.randomUUID();createdAt.current=new Date().toISOString();try{window.localStorage.setItem(`market-evidence-agent:local-chat-id:${getChatMode()}:v1`,localId.current);}catch{}apply(line,{restoring:false,conversationId:null,messages:[],historyHasMore:false,historyBefore:null,...(keepDraft?{}:{draft:""}),state:verified ? "ready" : "idle",status:"",loaded:true}); };
  const clear = () => clearLine(false);
  async function selectBot(next:Bot|null){
    const prev=lineRef.current, line=lineKey(next,null), switched=prev!==line;botRef.current=next;setBot(next);
    earlierController.current?.abort();loadingEarlierRef.current=false;setLoadingEarlier(false);
    if(switched){
      // Leave the old line running in the background: park its view and show the target line's own state.
      lines.current.update(prev,{messages:latestMessages.current});
      lineRef.current=line;lines.current.setActive(line);
      const s=lines.current.get(line), text=s.draft||loadDraft(line);
      setMessages(s.messages);latestMessages.current=s.messages;setState(s.state as State);setStatus(s.status);setConversationId(s.conversationId);setHistoryHasMore(s.historyHasMore);setHistoryBefore(s.historyBefore);setRestoring(s.restoring);setBackground(s.background ?? null);setDraftState(text);s.draft=text;setArchiveView(null);bump(n=>n+1);
    }
    if(!next)return;
    { const cur=lines.current.get(line); if(cur.state==="sending"||cur.restoring)return; }
    // Each bot has one line: open it, or start empty when the bot has not spoken yet.
    if(next.conversation_id){if(next.conversation_id!==lines.current.get(line).conversationId)await openConversation(next.conversation_id);}
    else if(switched)clearLine(true);
  }
  // FP13-c: the turns of the open conversation that this page did not watch finish (the divider), and the background banner's own functions.
  const awayTurns = conversationId ? (awayByConv[conversationId] ?? []) : [];
  // The poll and the send-time sync share one merge: whole turns only, the chat-sync plan, then the background's bookkeeping.
  function mergeTail(line:string, target:string, page:{messages:AgentChatMessage[]}) {
    const cur = lines.current.get(line), plan = planTailSync(cur, completeTurnsOnly(page.messages), target), bg = cur.background;
    if (plan) {
      const arrived = newTurnIds(cur.messages, plan.messages), marker = loadDetached(localStore(), target), ownTurnId = marker?.turnId ?? bg?.turnId ?? null;
      const split = arrivalSplit({ arrived, messages: plan.messages, ownTurnId, background: bg });
      apply(line, { messages: plan.messages });
      if (split.clearBackground) apply(line, { background: null, status: "" });
      if (split.ownArrived) dropDetached(localStore(), target);
      if (split.away.length) setAwayByConv(m => ({ ...m, [target]: [...(m[target] ?? []), ...split.away] }));
      setExternalTurns(known => [...known, ...split.external]); setFreshExternal(true);
    } else if (bg && backgroundExpired(bg, Date.now())) {
      apply(line, { background: null, status: t("后台那一轮一直没有结果出现，可能已被中断；需要的话可以再发一次。") });
      dropDetached(localStore(), target);
    }
  }
  async function syncBeforeSend(line:string) {
    const cid = lines.current.get(line).conversationId; if (!cid) return;
    try { const page = await restoreAgentChat(cid, undefined, true, null, 6); if (lineRef.current === line && lines.current.get(line).conversationId === cid) mergeTail(line, cid, page); }
    catch { /* a failed sync is not a failed send: the send goes on */ }
  }
  // Stop a turn this page started and then let go of (its stop button was pressed while it was still watched).  The list is touched only if the stopped placeholder is still the last message.
  async function stopDetached(line:string, cid:string, turnId:string|undefined) {
    const result = await cancelAgentTurn(cid, turnId ?? null);
    if (result.cancelled) { dropDetached(localStore(), cid); return; }
    const cur = lines.current.get(line), last = cur.messages.at(-1);
    const placeholder = cur.state !== "sending" && last?.role === "assistant" && last.status === "cancelled" && (turnId ? last.turn_id === turnId : true);
    const gone = result.reason === "no_running_turn" || result.reason === "turn_mismatch";
    if (gone) markDetachedGone(localStore(), cid);
    if (!placeholder) return;
    if (result.reason === "unreachable") { apply(line, { messages: cur.messages.slice(0, -1), background: { conversationId: cid, turnId: turnId ?? null, reason: "stop_unreachable", at: Date.now() } }); return; }
    if (gone) apply(line, { messages: cur.messages.slice(0, -1), status: t("这一轮在停止前已经答完，结果会自动出现在这里。") });
  }
  // The banner's stop button (§3.3): asks the server to stop the background turn and reports what it said.
  async function cancelBackground() {
    const line = lineRef.current, bg = lines.current.get(line).background, cid = bg?.conversationId;
    if (!bg || !cid) return;
    const result = await cancelAgentTurn(cid, bg.turnId ?? null);
    if (result.cancelled) { dropDetached(localStore(), cid); apply(line, { background: null, status: t("已请求停止后台回答。") }); return; }
    if (result.reason === "no_running_turn" || result.reason === "turn_mismatch") { markDetachedGone(localStore(), cid); apply(line, { background: null, status: bg.turnId ? t("后台那一轮已经结束，结果会自动出现在这里。") : t("没有能从这里停止的回答：它可能刚好答完（现在可以再发），也可能来自 Telegram 或未刷新的旧页面（只能等它答完）。") }); return; }
    apply(line, { status: t("没能连上服务器，稍后再试。") });
  }
  // A restored conversation: the note says a turn of this page was running (§3.7).  Arrived turns get the divider; a running one is shown with its question.
  function resumeLine(line:string, cid:string, messages:AgentChatMessage[]) {
    const store = localStore(), plan = resumePlan({ marker: loadDetached(store, cid), messages, now: Date.now() });
    if (plan.kind === "none") return;
    if (plan.kind === "running") { apply(line, { messages: [...messages, { role: "user", content: plan.question }], background: { conversationId: cid, turnId: plan.turnId, reason: "restored", at: plan.at } }); return; }
    dropDetached(store, cid);
    if (plan.kind === "arrived" && plan.away) { const turnId = plan.turnId; setAwayByConv(m => ({ ...m, [cid]: [...(m[cid] ?? []), turnId] })); }
    if (plan.kind === "expired") apply(line, { status: t("后台那一轮一直没有结果出现，可能已被中断；需要的话可以再发一次。") });
  }
  const visibleMessages=archiveView?archiveView.messages as AgentChatMessage[]:messages;
  return <Context.Provider value={{ conversationId,verified:verified||Boolean(bot), state, status, restoring,messages:visibleMessages, historyHasMore, loadingEarlier, loadEarlier, draft, setDraft, send, choose, chooseOptions, replyToCard, cancel, clear,openConversation,lineStatus:{running:lines.current.running(),unseen:lines.current.unseen(),waiting:lines.current.waiting()},archive,archiveView,fileName,archiveStatus,connectFile,disconnectFile,exportArchive,importArchive,selectArchive,returnLive,bot,selectBot , freshExternal, ackExternal: () => setFreshExternal(false), externalTurns, retry, notices, compactNow, background, cancelBackground, awayTurns }}>{children}</Context.Provider>;
}
function readLocalConversationId(){try{const key=`market-evidence-agent:local-chat-id:${getChatMode()}:v1`,existing=window.localStorage.getItem(key);if(existing&&/^[\w-]{1,80}$/.test(existing))return existing;const id=crypto.randomUUID();window.localStorage.setItem(key,id);return id;}catch{return crypto.randomUUID();}}
function archiveMessages(messages:AgentChatMessage[]){return messages.filter(m=>m.role==="user"||m.role==="assistant").map(m=>({role:m.role as "user"|"assistant",content:m.content,...(m.status?{status:m.status as "failed"|"cancelled"}:{}),...(m.role==="assistant"&&m.citations?{citations:m.citations}:{}),...(m.role==="assistant"&&m.unverified_lines?.length?{unverified_lines:m.unverified_lines}:{}),...(m.role==="assistant"&&m.tool_trace?{tool_trace:m.tool_trace.map(x=>({call_id:x.call_id,name:x.name,arguments:x.arguments,result:x.result,status:x.status as "running"|"complete"|"not_found"|"failed"|"cancelled"}))}:{})}));}
export function useChat() { const value = useContext(Context); if (!value) throw new Error("Agent chat provider is missing"); return value; }
/** Open one of the caller's stored conversations (memory page, #agent/<id> links). */
export function useOpenConversation() { return useChat().openConversation; }
/** Open a bot's line (its turns then carry only bot_id), or leave every bot's line with null. */
export function useSelectBot() { return useChat().selectBot; }
/** Which bots' lines are answering in the background, and which finished an answer the user has not opened yet (local state, apart from the server's bot.unread). */
export function useLineStatus() { return useChat().lineStatus; }
