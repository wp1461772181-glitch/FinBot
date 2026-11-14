import { agentChatUrl } from "../agent-chat-url.mjs";
import { fetchAgentChatModels } from "../agent-chat-models.mjs";
import { type CompactionNotice, type ContextUsage, normalizeCompactions, normalizeContextUsage } from "../context-usage.mjs";
import { conversationCreatedAtForMode, conversationForMode, selectConversationForMode } from "../chat-identity.mjs";
import type { FlowNode } from "../turn-flow.mjs";
import type { UnverifiedLine } from "../chat-unverified.mjs";
import { ApiError, apiErrorFromPayload, chatCredential, configuredApiBaseUrl } from "./base";

export type AgentChatProvider = "deepseek" | "kimi" | "minimax" | "qwen" | "zhipu" | "doubao" | "hunyuan" | "baidu" | "siliconflow" | "openrouter" | "custom";
export type AgentChatConfig = { provider: AgentChatProvider; base_url?: string; model: string; api_key: string };
export type AgentCitation = { ordinal?:number; chunk_id?: string | null; document_id?: string | null; title: string; section: string; source_url?: string | null; observed_at?: string | null; published_at?:string|null; quote?:string; source_type: string; truncated: boolean; derived?:boolean };

export type AgentClarification = {request_id:string;reason:string;question?:string;display?:{title?:string;agent_suggestion?:boolean;saved_date?:string;web_date?:string;url?:string;alternative?:string;targets?:Array<Record<string,string>>};choices:Array<{label:string;value:string}>;options?:Array<{value:string;label:string;detail?:string}>;select?:{min:number;max:number}};

export type AgentChatMessage = { citation_protocol?: string; citation_nodes?: { source_ref: string; citation_id?: string; quote?: string }[]; unverified_lines?: UnverifiedLine[]; public_marks?: unknown[]; role: "user" | "assistant" | "tool"; content: string; status?: string; turn_id?: string; reused_sources?: boolean; citations?: AgentCitation[]; clarification?: AgentClarification; tool_calls?: Array<{ id: string; function: { name: string; arguments: string } }>; tool_call_id?: string; tool_trace?: Array<{ call_id?: string; name: string; arguments?: unknown; result?: unknown; status: string; card?: boolean }>; trace?: FlowNode[]; thinking_ms?: number; started_at?: number };
export type AgentChatEvent = { event: string; data: Record<string, unknown> };
const chatConversationKey = "market-evidence-agent:chat-conversation:v1";

export async function personalChatLogin(code: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, "personal-login"), { method:"POST", signal, cache:"no-store", headers:{Accept:"application/json","Content-Type":"application/json"}, body:JSON.stringify({code}) });
  const payload = await response.json().catch(()=>null) as {credential?:unknown}|null;
  if (!response.ok || typeof payload?.credential !== "string") throw new ApiError("个人登录暂不可用。", response.status);
  return payload.credential;
}
export type ConversationSummary = { id:string; title:string; created_at:string; updated_at:string; custom_title?:boolean };
export type { CompactionNotice, ContextUsage };
/** What the next message of this conversation carries of the earlier ones, by part; null when it cannot be read.
 *  Without an id it is the fixed part only (a conversation that has not started). */
export async function getContextUsage(id:string|null,signal?:AbortSignal,botId?:string|null): Promise<ContextUsage|null> {
  const base = agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, "");
  const query = botId ? `?bot_id=${encodeURIComponent(botId)}` : "";    // the bot's model sets the window, hence the budget
  const url = (id ? `${base}conversations/${encodeURIComponent(id)}/context` : `${base}context`) + query;
  const response = await fetch(url,{signal,cache:"no-store",headers:{Accept:"application/json","X-Chat-Session":chatCredential()}});
  if(!response.ok) return null;
  return normalizeContextUsage(await response.json().catch(()=>null));
}
/** Compress the conversation now (the 「/压缩」 command and the context card's button).  The bot's own model does it. */
export async function compactConversation(id:string,botId:string|null,focus:string,signal?:AbortSignal): Promise<{compacted:number;message:string}> {
  const base = agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, "");
  const response = await fetch(`${base}conversations/${encodeURIComponent(id)}/compact`,{method:"POST",signal,cache:"no-store",
    headers:{Accept:"application/json","Content-Type":"application/json","X-Chat-Session":chatCredential()},
    body:JSON.stringify({focus:focus||null,bot_id:botId})});
  const data=await response.json().catch(()=>null) as {compacted?:unknown;message?:unknown}|null;
  if(!response.ok) throw new ApiError("压缩没有成功，稍后再试。",response.status);
  return {compacted:typeof data?.compacted==="number"?data.compacted:0,message:typeof data?.message==="string"&&data.message?data.message:"完成。"};
}
/** Name one of the caller's conversations; resolves to the saved name, or null when it was cleared. */
export async function renameAgentConversation(id:string,title:string,signal?:AbortSignal): Promise<string|null> {
  const url = agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, `conversations/${encodeURIComponent(id)}`);
  const response = await fetch(url,{method:"PATCH",signal,cache:"no-store",headers:{Accept:"application/json","Content-Type":"application/json","X-Chat-Session":chatCredential()},body:JSON.stringify({title})});
  if(!response.ok) throw new ApiError(response.status===404?"找不到这个对话。":response.status===422?"名称无效或超过 80 个字。":"重命名失败，请重试。",response.status);
  const data=await response.json().catch(()=>null) as {title?:unknown}|null;
  return typeof data?.title==="string"&&data.title?data.title:null;
}
/** Archive (hide) or restore one of this credential's conversations: a logical delete. */
export async function archiveAgentConversation(id:string,archived=true,signal?:AbortSignal): Promise<boolean> {
  const url = agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, `conversations/${encodeURIComponent(id)}`);
  const response = await fetch(url,{method:"PATCH",signal,cache:"no-store",headers:{Accept:"application/json","Content-Type":"application/json","X-Chat-Session":chatCredential()},body:JSON.stringify({archived})});
  if(!response.ok) throw new ApiError(response.status===404?"找不到这个对话。":"归档失败，请重试。",response.status);
  return true;
}
/** The owner's research queue as the server keeps it: null until one was saved.  Owner only. */

export async function listAgentConversations(offset=0,signal?:AbortSignal): Promise<{conversations:ConversationSummary[];hasMore:boolean}> {
  const url = agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, `conversations?limit=30&offset=${offset}`);
  const response = await fetch(url,{signal,cache:"no-store",headers:{Accept:"application/json","X-Chat-Session":chatCredential()}});
  if(!response.ok) throw new ApiError("历史对话暂时无法加载。",response.status);
  const data=await response.json() as {conversations?:unknown;has_more?:unknown};
  return {conversations:Array.isArray(data.conversations)?data.conversations as unknown as ConversationSummary[]:[],hasMore:data.has_more===true};
}
export async function restoreAgentChat(selectedId?: string | null, signal?: AbortSignal, requireExisting=false, before?: number | null, limit=20): Promise<{ conversationId: string | null; createdAt:string|null; messages: AgentChatMessage[]; hasMore:boolean; nextBefore:number|null; compactions?:CompactionNotice[] }> {
  const conversationId = selectedId ?? conversationForMode(window.localStorage) ?? window.sessionStorage.getItem(chatConversationKey);
  if (!conversationId) return { conversationId: null, createdAt:null, messages: [], hasMore:false, nextBefore:null };
  const params = new URLSearchParams({ limit: String(limit) });
  if (before !== undefined && before !== null) params.set("before", String(before));
  const response = await fetch(agentChatUrl("messages", configuredApiBaseUrl).replace(/messages$/, `conversations/${encodeURIComponent(conversationId)}/messages`) + `?${params.toString()}`, {
    signal, headers: { Accept: "application/json", "X-Chat-Session": chatCredential() }, cache: "no-store",
  });
  if (response.status === 404) { if(requireExisting)throw new ApiError("无法恢复服务端聊天记录。",404); return { conversationId: null, createdAt:null, messages: [], hasMore:false, nextBefore:null }; }
  if (!response.ok) throw new ApiError("无法恢复服务端聊天记录。", response.status);
  const data = await response.json() as { messages?: AgentChatMessage[]; has_more?:unknown; next_before?:unknown; compactions?:unknown };
  return { conversationId, createdAt:conversationCreatedAtForMode(window.localStorage), messages: Array.isArray(data.messages) ? data.messages : [],
    compactions: normalizeCompactions(data.compactions),
    hasMore: data.has_more === true, nextBefore: typeof data.next_before === "number" ? data.next_before : null };
}
export function clearAgentConversation(): void { selectConversationForMode(window.localStorage,window.sessionStorage,null); }
export function selectAgentConversation(id:string|null,createdAt?:string|null):void { selectConversationForMode(window.localStorage,window.sessionStorage,id,undefined,createdAt); }
export async function agentChatStream(config: AgentChatConfig | { bot_id: string } | { catalog_model: string }, message: string, conversationId: string | null, signal: AbortSignal, onEvent: (event: AgentChatEvent) => boolean | void, pendingRequestId?:string, displayMessage?:string): Promise<string> {
  const response = await fetch(agentChatUrl("stream", configuredApiBaseUrl), { method: "POST", signal, cache: "no-store", headers: { Accept: "text/event-stream", "Content-Type": "application/json", "X-Chat-Session": chatCredential() }, body: JSON.stringify({ ...config, message, conversation_id: conversationId, ...(pendingRequestId?{pending_request_id:pendingRequestId,...(displayMessage?{display_message:displayMessage}:{})}:{}) }) });
  if (!response.ok) { const payload = await response.json().catch(() => null); throw apiErrorFromPayload(payload, response.status); }
  const reader = response.body?.getReader(); if (!reader) throw new ApiError("服务未返回流式响应。");
  const decoder = new TextDecoder(); let buffer = "", answer = "", eventName = "message", receivedDone = false;
  while (true) {
    const { value, done } = await reader.read(); buffer += decoder.decode(value, { stream: !done });
    let boundary; while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2); let raw = "";
      for (const line of chunk.split(/\r?\n/)) { if (line.startsWith("event:")) eventName = line.slice(6).trim(); else if (line.startsWith("data:")) raw += line.slice(5).trim(); }
      if (!raw) continue; let data: Record<string, unknown>; try { data = JSON.parse(raw); } catch { throw new ApiError("服务返回了无效的聊天事件。"); }
      if (eventName === "delta" && typeof data.text === "string") answer += data.text;
      const receivedEvent = eventName;
      const accepted = onEvent({ event: receivedEvent, data });
      if (accepted === false) { await reader.cancel().catch(() => {}); return answer; }
      if (receivedEvent === "conversation" && typeof data.conversation_id === "string") window.sessionStorage.setItem(chatConversationKey, data.conversation_id);
      if (receivedEvent === "done" && ["complete","succeeded","partially_succeeded","waiting_for_input","running","failed"].includes(String(data.status))) receivedDone = true;
      eventName = "message";
      if (receivedEvent === "error") throw new ApiError(String(data.code ?? "chat_failed"));
    }
    if (done) break;
  }
  if (!receivedDone) throw new ApiError("provider_incomplete_stream");
  return answer;
}
export async function agentChatRequest(path: "hello" | "messages", config: AgentChatConfig, messages: AgentChatMessage[], signal: AbortSignal): Promise<{ content: string; model: string }> {
  const response = await fetch(agentChatUrl(path, configuredApiBaseUrl), {
    method: "POST", signal, cache: "no-store",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ ...config, messages }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw apiErrorFromPayload(payload, response.status);
  return payload as { content: string; model: string };
}

export async function agentChatModels(config: Pick<AgentChatConfig, "provider" | "base_url"> & Partial<Pick<AgentChatConfig,"api_key">>, signal: AbortSignal): Promise<{status:string;ordering:string;models:Array<{id:string;name:string}>}> {
  const response = await fetchAgentChatModels(config, signal, configuredApiBaseUrl);
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {detail?:unknown}|null;
    const code = typeof payload?.detail === "string" && /^[a-z0-9_]{1,80}$/.test(payload.detail) ? payload.detail : "model_discovery_unavailable";
    throw new ApiError(code, response.status);
  }
  const payload = await response.json() as {status?:unknown;ordering?:unknown;models?:unknown};
  return {status:typeof payload.status === "string"?payload.status:"empty",ordering:typeof payload.ordering === "string"?payload.ordering:"unknown",models:Array.isArray(payload.models)?payload.models.slice(0,5) as Array<{id:string;name:string}>:[]};
}

