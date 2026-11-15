import { ApiError, agentPath, ownerHeaders } from "./base";

export type ProfileItem = { id:string; handle:string; kind:"preference"|"about_me"|"instruction"; topic:string|null; text:string; origin:"explicit"|"inferred"|"manual"; quote:string; status:"active"|"archived"; scope:"global"|"bot"; bot_id:string|null; bot_name:string|null; created_at:string|null; updated_at:string|null; last_used_at:string|null };
export type ProfileBot = { id:string; name:string; is_default:boolean };
export type RecallItem = { conversation_id:string; title:string; date:string|null; summary:string; kind:"summary"|"questions"; link:string; bot_id:string|null; bot_name:string|null };

/** The owner's profile items, active and archived (memory page).  Owner only: a guest gets 403. */
export async function listProfileItems(signal?:AbortSignal): Promise<{items:ProfileItem[];bots:ProfileBot[]}> {
  const response = await fetch(agentPath("profile"),{signal,cache:"no-store",headers:ownerHeaders()});
  if(!response.ok) throw new ApiError(response.status===403?"登录个人聊天后才能查看记忆。":"画像暂时无法读取。",response.status);
  const data=await response.json().catch(()=>null) as {items?:unknown;bots?:unknown}|null;
  return {items:Array.isArray(data?.items)?data.items as ProfileItem[]:[],bots:Array.isArray(data?.bots)?data.bots as ProfileBot[]:[]};
}
/** The owner types an item on the memory page: global (bot_id null) or one bot's own memory. */
export async function createProfileItem(fields:{kind:ProfileItem["kind"];text:string;bot_id:string|null},signal?:AbortSignal): Promise<ProfileItem> {
  const response = await fetch(agentPath("profile"),{method:"POST",signal,cache:"no-store",headers:ownerHeaders(true),body:JSON.stringify(fields)});
  if(!response.ok) throw new ApiError(response.status===409?"已有一条你确认过的同类设定，先编辑或删除它。":response.status===422?"这条没法保存：内容为空、太长，或 bot 已不存在。":"保存失败，请重试。",response.status);
  return (await response.json() as {item:ProfileItem}).item;
}
/** The owner edits an item's text or moves it to another layer (bot_id null: global). */
export async function updateProfileItem(id:string,fields:{text?:string;bot_id?:string|null},signal?:AbortSignal): Promise<ProfileItem> {
  const response = await fetch(agentPath(`profile/${encodeURIComponent(id)}`),{method:"PATCH",signal,cache:"no-store",headers:ownerHeaders(true),body:JSON.stringify(fields)});
  if(!response.ok) throw new ApiError(response.status===404?"这条已不存在。":"保存失败，请重试。",response.status);
  return (await response.json() as {item:ProfileItem}).item;
}
export async function confirmProfileItem(id:string,signal?:AbortSignal): Promise<ProfileItem> {
  const response = await fetch(agentPath(`profile/${encodeURIComponent(id)}/confirm`),{method:"POST",signal,cache:"no-store",headers:ownerHeaders()});
  if(!response.ok) throw new ApiError(response.status===404?"这条已不存在。":"确认失败，请重试。",response.status);
  return (await response.json() as {item:ProfileItem}).item;
}
export async function deleteProfileItem(id:string,signal?:AbortSignal): Promise<void> {
  const response = await fetch(agentPath(`profile/${encodeURIComponent(id)}`),{method:"DELETE",signal,cache:"no-store",headers:ownerHeaders()});
  if(!response.ok&&response.status!==404) throw new ApiError("删除失败，请重试。",response.status);
}
/** The owner's past conversations: newest first, or the best matches for a query.  Memory, not evidence. */
export async function listRecall(query="",signal?:AbortSignal,botId?:string|null): Promise<RecallItem[]> {
  const params=new URLSearchParams(query.trim()?{q:query.trim()}:{limit:"20"});
  if(botId) params.set("bot_id",botId);
  const response = await fetch(agentPath(`recall?${params.toString()}`),{signal,cache:"no-store",headers:ownerHeaders()});
  if(!response.ok) throw new ApiError(response.status===403?"登录个人聊天后才能查看记忆。":"往事暂时无法读取。",response.status);
  const data=await response.json().catch(()=>null) as {items?:unknown}|null;
  return Array.isArray(data?.items)?data.items as RecallItem[]:[];
}
