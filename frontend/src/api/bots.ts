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
  key_source: "vault" | "env"; key_env: string | null; key_status: "configured" | "missing"; is_default: boolean; migrated: boolean;
  /** From the provider's model list (OpenRouter only).  Absent means unknown; supported_efforts null means every tier. */
  supported_efforts?: string[] | null; reasoning_supported?: boolean };
export type ModelCatalog = { models: CatalogModel[]; default: string | null; config_file: { present: boolean; problems: string[] } };
const BOT_ERRORS:Record<string,string>={invalid_name:"名字无效（1 到 40 字）。",name_taken:"已有同名 bot。",invalid_title:"头衔最多 60 字。",invalid_description:"说明最多 4000 字。",
  invalid_reasoning_effort:"推理强度不在可选范围内。",invalid_focus:"关注范围无效。",invalid_focus_symbol:"股票代码无效，例如 AAPL 或 BRK.B。",too_many_companies:"关注公司最多 20 家。",invalid_tool_scope:"工具范围无效。",
  unknown_tool:"工具范围里有不存在的工具。",unknown_model:"模型目录里没有这个模型。",unknown_role:"没有这个模型用途。",invalid_avatar:"头像最多 16 个字符。",invalid_look:"头像外观不在可选范围内。",invalid_group:"分组名最多 40 字。",
  default_bot_not_hidden:"默认 bot 不能隐藏。",default_bot_undeletable:"默认 bot 不能删除。",invalid_notify_cap:"每日通知上限为 0 到 50。",too_many_bots:"bot 已达上限（30 个）。",
  bot_not_found:"bot 不存在或已删除。",unknown_template:"模板无效。",unknown_skill:"这个技能不存在。",model_exists:"已有同名模型。",model_not_found:"模型不存在。",model_in_use:"有 bot 正在用这个模型，先给它们换模型。",
  model_name_in_code:"这个名字被服务器的代码或配置按名引用，不能改名。",model_from_file:"这个模型来自服务器配置文件，只能在服务器上改。",default_from_file:"默认模型由服务器配置文件指定。",invalid_provider:"模型服务无效。",invalid_model:"Model ID 无效。",
  invalid_endpoint:"接口地址无效：须为 HTTPS，自定义服务必须填写。",invalid_key:"API key 格式不对。",invalid_key_env:"环境变量名须以 _API_KEY 结尾，且不能是服务器自己的密钥。",
  one_key_source:"API key 和环境变量只能填一个。",key_required:"换了服务或接口地址，需要重新填写 key。",credential_key_missing:"服务器没有配置加密密钥，无法保存 key。",
  too_many_models:"模型已达上限（40 个）。",invalid_agent_chat_request:"填写的内容无效。",
  model_key_missing:"服务器上没有找到这个 key：检查环境变量名，或重新填写 key。",invalid_model_request:"Model ID 或接口地址无效。",model_not_configured:"模型目录是空的：先在设置里添加一个模型。"};
async function botJson<T>(path:string,init:{method?:string;body?:unknown;signal?:AbortSignal},failure:string):Promise<T>{
  const response=await fetch(agentPath(path),{method:init.method??"GET",signal:init.signal,cache:"no-store",headers:ownerHeaders(init.body!==undefined),
    ...(init.body!==undefined?{body:JSON.stringify(init.body)}:{})});
  if(!response.ok){
    const detail=(await response.json().catch(()=>null) as {detail?:unknown}|null)?.detail;
    throw new ApiError(response.status===403||response.status===401?"登录个人聊天后才能使用 bot。":(typeof detail==="string"&&BOT_ERRORS[detail])||failure,response.status);
  }
  return await response.json() as T;
}
export async function listBots(signal?:AbortSignal):Promise<{bots:Bot[];default_bot_id:string|null}>{ return await botJson("bots",{signal},"bot 列表暂时无法读取。"); }

export async function updateBot(id:string,fields:BotFields):Promise<Bot>{ return (await botJson<{bot:Bot}>(`bots/${encodeURIComponent(id)}`,{method:"PATCH",body:fields},"保存失败，请重试。")).bot; }

export async function getModelCatalog(signal?:AbortSignal):Promise<ModelCatalog>{ return await botJson("model-catalog",{signal},"模型目录暂时无法读取。"); }

// Shared with the sibling API modules (kept off the declarations so they stay byte-identical to the original).
export { botJson };
