import { ownerJson } from "./owner";

export type InboxSource = { ordinal:number; title:string; url:string|null; source_type:string|null; published_at?:string|null };
export type InboxItem = { id:string; section:"brief"|"confirm"; kind:"task_brief"|"filing"|"news"|"price"|"action"; title:string; body:string; sources:InboxSource[];
  payload:{ task_name?:string; channel_pending?:string; missed_slots?:number; display?:{ title?:string; targets?:unknown[]; alternative?:string }; confirmation_state?:string; action_token?:string; short_code?:string; event_id?:string };
  confirmation_state?:"pending_confirm"|"confirmed"|"skipped"|"expired"; action_token?:string|null; short_code?:string|null;
  actions?:Array<{ id:"confirm"|"skip"|"later"; label:string; kind:string }>;
  task_id:string|null; bot_id:string|null; posted:boolean; conversation_id:string|null; status:"unread"|"read"|"done"|"dismissed"; created_at:string|null };

/** A routine card a bot proposed in chat that the owner has not pressed yet (expired: its press no longer runs). */
export type TaskProposal = { id:string; conversation_id:string; bot_id:string|null; tools:string[]; title:string|null; targets:Array<Record<string,string>>; detail:string|null; expires_at:string; expired:boolean; created_at:string|null };
export async function listTaskProposals(signal?:AbortSignal):Promise<TaskProposal[]>{ return (await ownerJson<{proposals:TaskProposal[]}>("tasks/proposals",{signal},"任务暂时无法读取。")).proposals; }
export async function markBotRead(botId:string):Promise<number>{ return (await ownerJson<{read:number}>(`bots/${encodeURIComponent(botId)}/read`,{method:"POST"},"操作失败，请重试。")).read; }

export async function listInbox(section?:"brief"|"confirm",signal?:AbortSignal,botId?:string):Promise<InboxItem[]>{
  const query=[section&&`section=${section}`,botId&&`bot_id=${encodeURIComponent(botId)}`].filter(Boolean).join("&");
  return (await ownerJson<{items:InboxItem[]}>(query?`inbox?${query}`:"inbox",{signal},"简报暂时无法读取。")).items;
}
