import { ApiError, agentPath, ownerHeaders } from "./base";
import type { Bot } from "./bots";

// Scheduled tasks, the inbox and the background model (owner only).  The background key is sent once
// when saved and never comes back: the server answers with has_key only.

async function ownerJson<T>(path:string,init:{method?:string;body?:unknown;signal?:AbortSignal},failure:string):Promise<T>{
  const response=await fetch(agentPath(path),{method:init.method??"GET",signal:init.signal,cache:"no-store",headers:ownerHeaders(init.body!==undefined),
    ...(init.body!==undefined?{body:JSON.stringify(init.body)}:{})});
  if(!response.ok){
    const detail=(await response.json().catch(()=>null) as {detail?:unknown}|null)?.detail;
    throw new ApiError(response.status===403||response.status===401?"登录个人聊天后才能使用简报和任务。":(typeof detail==="string"&&TASK_ERRORS[detail])||failure,response.status);
  }
  return await response.json() as T;
}
const TASK_ERRORS:Record<string,string>={invalid_schedule:"时间格式应为 HH:MM。",invalid_timezone:"时区无效。",invalid_instruction:"请写任务说明（最多 2000 字）。",
  invalid_symbols:"股票代码无效，或指定公司时没有填代码。",invalid_price_lines:"价格线无效：填股票代码和上穿或下穿的价格。",invalid_every:"间隔无效：小时 1 到 720，天 1 到 365，周 1 到 52。",invalid_max_runs:"执行次数无效：填 1 到 1000 的整数，或不限。",
  too_many_tasks:"任务已达上限（20 个）。",invalid_name:"请填任务名称（最多 80 字）。",key_required:"请填写 API key。",invalid_key:"API key 格式不对。",
  invalid_endpoint:"接口地址无效：须为 HTTPS，自定义服务必须填写。",credential_key_missing:"服务器没有配置加密密钥，无法保存 key。",invalid_agent_chat_request:"填写的内容无效。",token_in_use:"这个 token 已经用在别的 bot 上了：一个 Telegram bot 只能接一个 bot。",bind_code_expired:"绑定码已过期，请重新生成。",
  invalid_bot_token:"Bot Token 格式无效：应从 BotFather 获取。",no_bot_token:"请先保存 Bot Token。",
  no_active_bind:"没有正在进行的绑定。",bind_code_mismatch:"绑定码不匹配。",bind_already_confirmed:"已绑定，请勿重复确认。",
  not_bound:"尚未绑定任何 Telegram 账号。",invalid_bind_code:"绑定码格式无效。",invalid_chat_id:"Chat ID 无效。",unknown_bot:"这个 bot 不存在或不是你的。",
  unknown_skill:"这个技能不存在。"};

// Shared with the sibling API modules (kept off the declarations so they stay byte-identical to the original).
export { TASK_ERRORS, ownerJson };
