import { ownerJson } from "./owner";
import type { InboxItem } from "./inbox";

export async function setInboxStatus(id:string,status:InboxItem["status"]):Promise<InboxItem>{
  return (await ownerJson<{item:InboxItem}>(`inbox/${encodeURIComponent(id)}/status`,{method:"POST",body:{status}},"操作失败，请重试。")).item;
}
/** Mint the confirmation card of a 待你确认 item in its conversation; open that conversation to press it. */
export async function mintInboxCard(id:string):Promise<{conversation_id:string;request_id:string;expires_at:string|null}>{
  return await ownerJson(`inbox/${encodeURIComponent(id)}/card`,{method:"POST"},"生成确认卡失败，请重试。");
}
/** Inline confirmation on a 待你确认 card without leaving the 例行任务 / 通知列表 page. */
export async function confirmInboxItem(id:string,action:"confirm"|"skip"|"later",actionToken?:string|null):Promise<{ok:boolean;state:string;message?:string;item:InboxItem|null}>{
  return await ownerJson(`inbox/${encodeURIComponent(id)}/confirm`,{method:"POST",body:{action,...(actionToken?{action_token:actionToken}:{})}},"确认失败，请重试。");
}
