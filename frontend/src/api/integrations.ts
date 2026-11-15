import { ownerJson } from "./owner";

export type BackgroundModel = { configured:boolean; has_key:boolean; provider?:string; model?:string; base_url?:string|null; revoked_at?:string|null; updated_at?:string|null };

export async function getBackgroundModel(signal?:AbortSignal):Promise<BackgroundModel>{ return await ownerJson("background-model",{signal},"后台模型设置暂时无法读取。"); }
export async function saveBackgroundModel(value:{provider:string;model:string;base_url?:string|null;api_key?:string}):Promise<BackgroundModel>{
  return await ownerJson("background-model",{method:"PUT",body:value},"保存失败。");
}
export async function revokeBackgroundKey():Promise<BackgroundModel>{ return await ownerJson("background-model/key",{method:"DELETE"},"撤销失败，请重试。"); }
export type TelegramBindStatus = { configured:boolean; has_token:boolean; bound:boolean; bot_username?:string|null; chat_id?:number|null; bound_at?:string|null; bind_code_active?:boolean };
export async function getTelegramBind(signal?:AbortSignal):Promise<TelegramBindStatus>{ return await ownerJson("telegram/status",{signal},"Telegram 设置暂时无法读取。"); }
export async function saveTelegramToken(token:string):Promise<TelegramBindStatus>{
  return await ownerJson("telegram/token",{method:"POST",body:{bot_token:token}},"保存失败。");
}
export type PushoverStatus = { configured:boolean; updated_at:string|null };
export async function getPushover(signal?:AbortSignal):Promise<PushoverStatus>{ return await ownerJson("pushover/status",{signal},"Pushover 设置暂时无法读取。"); }
export async function savePushover(userKey:string,appToken:string):Promise<PushoverStatus>{
  return await ownerJson("pushover",{method:"PUT",body:{user_key:userKey,app_token:appToken}},"Pushover 的 key 格式不对（应为 30 位字母数字）。");
}
export async function clearPushover():Promise<PushoverStatus>{ return await ownerJson("pushover",{method:"DELETE"},"操作失败，请重试。"); }
export async function startTelegramBind():Promise<{code:string;bot_username?:string|null}>{
  return await ownerJson("telegram/bind",{method:"POST"},"生成绑定码失败。");
}
export async function unbindTelegram():Promise<TelegramBindStatus>{
  return await ownerJson("telegram/unbind",{method:"POST"},"解绑失败。");
}
// A bot's own Telegram bot (UX batch 2, P4).  The default bot's is the shared one above.
export type BotTelegramStatus = TelegramBindStatus & { shared:boolean; status?:"none"|"unbound"|"running"|"invalid"|"conflict"; token_tail?:string|null; last_error?:string|null };
const botTelegram=(botId:string,rest="")=>`bots/${encodeURIComponent(botId)}/telegram${rest}`;
export async function getBotTelegram(botId:string,signal?:AbortSignal):Promise<BotTelegramStatus>{ return await ownerJson(botTelegram(botId),{signal},"Telegram 设置暂时无法读取。"); }
export async function saveBotTelegramToken(botId:string,token:string):Promise<BotTelegramStatus>{ return await ownerJson(botTelegram(botId,"/token"),{method:"POST",body:{bot_token:token}},"保存失败：token 无效，或已用在别的 bot 上。"); }
export async function startBotTelegramBind(botId:string):Promise<{code:string;bot_username?:string|null;link?:string|null;expires_at:string}>{ return await ownerJson(botTelegram(botId,"/bind"),{method:"POST"},"生成绑定码失败。"); }
export async function unbindBotTelegram(botId:string):Promise<BotTelegramStatus>{ return await ownerJson(botTelegram(botId,"/unbind"),{method:"POST"},"解绑失败。"); }
export async function deleteBotTelegram(botId:string):Promise<BotTelegramStatus>{ return await ownerJson(botTelegram(botId),{method:"DELETE"},"删除失败。"); }
