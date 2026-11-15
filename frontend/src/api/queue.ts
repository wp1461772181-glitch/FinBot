import { agentChatUrl } from "../agent-chat-url.mjs";
import { ApiError, chatCredential, configuredApiBaseUrl } from "./base";

export async function getResearchQueue(signal?:AbortSignal): Promise<string[]|null> {
  const url = agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, "research-queue");
  const response = await fetch(url,{signal,cache:"no-store",headers:{Accept:"application/json","X-Chat-Session":chatCredential()}});
  if(!response.ok) throw new ApiError("研究队列暂时无法读取。",response.status);
  const data=await response.json().catch(()=>null) as {symbols?:unknown}|null;
  return Array.isArray(data?.symbols)?data.symbols.filter((item):item is string=>typeof item==="string"):null;
}
export async function putResearchQueue(symbols:string[],signal?:AbortSignal): Promise<void> {
  const url = agentChatUrl("stream", configuredApiBaseUrl).replace(/stream$/, "research-queue");
  const response = await fetch(url,{method:"PUT",signal,cache:"no-store",headers:{Accept:"application/json","Content-Type":"application/json","X-Chat-Session":chatCredential()},body:JSON.stringify({symbols})});
  if(!response.ok) throw new ApiError("研究队列保存失败。",response.status);
}
