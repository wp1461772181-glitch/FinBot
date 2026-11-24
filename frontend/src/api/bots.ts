import { ApiError, agentPath, ownerHeaders } from "./base";

// Bots (personal agent, second edition).  A bot's turn sends only bot_id: the server picks the model from its
// catalog, so no key leaves the browser.  Catalog entries say configured / missing, never the key.
export type BotFocus = { companies: Array<{ symbol: string; name?: string | null }>; theme: string | null };
export type Bot = { id: string; name: string; title: string; description: string; focus: BotFocus; tool_scope: string[] | null; model: string | null; reasoning_effort: string | null;
  skills: string[]; avatar: string; look: { shape: string; color: string } | null; group: string; pinned: boolean; hidden: boolean; is_default: boolean; template: string; conversation_id: string | null;
  daily_notify_cap: number; default_company: { symbol: string; company: string | null } | null; last_message: string | null; last_at: string | null; unread: number; pending: number;
  created_at?: string | null; updated_at?: string | null };
export type BotTemplate = { id: string; label: string; name: string; title: string; description: string; tool_scope: string[] | null };
export type BotTool = { name: string; level: string; owner_only: boolean };
export type BotFields = Partial<Pick<Bot, "name" | "title" | "description" | "focus" | "tool_scope" | "model" | "reasoning_effort" | "avatar" | "look" | "group" | "pinned" | "hidden" | "template" | "daily_notify_cap" | "skills">>;
export type CatalogModel = { name: string; display_name: string; provider: string; model: string; base_url: string | null; origin: "file" | "server";
  key_source: "vault" | "env"; key_env: string | null; key_status: "configured" | "missing";
  /** The head and tail of a key kept on the server (vault entries with a readable key only); never the whole key. */
  key_hint?: string; is_default: boolean; migrated: boolean;
  /** From the provider's model list (OpenRouter only).  Absent means unknown; supported_efforts null means every tier. */
  supported_efforts?: string[] | null; reasoning_supported?: boolean;
  /** Optional prices in USD per million tokens (null: not set); ``price_since`` is when one last changed. */
  price_input?: number | null; price_output?: number | null; price_cache_read?: number | null; price_cache_write?: number | null; price_since?: string | null };
export type ModelCatalog = { models: CatalogModel[]; default: string | null; config_file: { present: boolean; problems: string[] } };
// The sentences of the server's refusal codes live in bot-errors.ts, a chunk of its own (1.25 kB gzipped): only a request that failed needs one, so the first screen does not carry them.
async function botErrorText(code:string):Promise<string|undefined>{ try{ return (await import("./bot-errors")).BOT_ERRORS[code]; }catch{ return undefined; } }
async function botJson<T>(path:string,init:{method?:string;body?:unknown;signal?:AbortSignal},failure:string):Promise<T>{
  const response=await fetch(agentPath(path),{method:init.method??"GET",signal:init.signal,cache:"no-store",headers:ownerHeaders(init.body!==undefined),
    ...(init.body!==undefined?{body:JSON.stringify(init.body)}:{})});
  if(!response.ok){
    const detail=(await response.json().catch(()=>null) as {detail?:unknown}|null)?.detail;
    throw new ApiError(response.status===403||response.status===401?"登录个人聊天后才能使用 bot。":(typeof detail==="string"&&await botErrorText(detail))||failure,response.status);
  }
  return await response.json() as T;
}
export async function listBots(signal?:AbortSignal):Promise<{bots:Bot[];default_bot_id:string|null}>{ return await botJson("bots",{signal},"bot 列表暂时无法读取。"); }

export async function updateBot(id:string,fields:BotFields):Promise<Bot>{ return (await botJson<{bot:Bot}>(`bots/${encodeURIComponent(id)}`,{method:"PATCH",body:fields},"保存失败，请重试。")).bot; }

export async function getModelCatalog(signal?:AbortSignal):Promise<ModelCatalog>{ return await botJson("model-catalog",{signal},"模型目录暂时无法读取。"); }

// Shared with the sibling API modules (kept off the declarations so they stay byte-identical to the original).
export { botJson };
