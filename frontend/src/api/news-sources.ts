import { ownerJson } from "./owner";

export type NewsPushSettings = { summary_max_tokens: number; presets?: Array<{ label: string; value: number }> };
export type NewsSource = {
  id: string;
  name: string;
  enabled: boolean;
  kind: "rss" | "http_json" | "http_html";
  url: string;
  homepage?: string;
  language?: string;
  tags?: string[];
  markets?: string[];
  health: "ok" | "degraded" | "failed" | string;
  rea_repair: boolean;
  alternates?: string[];
  consecutive_failures?: number;
  last_error?: string | null;
};
export type NewsSourceInput = {
  id: string;
  name?: string;
  enabled?: boolean;
  kind: "rss" | "http_json" | "http_html";
  url: string;
  homepage?: string;
  language?: string;
  tags?: string[];
  markets?: string[];
  rea_repair?: boolean;
  alternates?: string[];
};
export type NewsDryRunResult = {
  ok: boolean;
  source_id?: string;
  raw_count?: number;
  valid_count?: number;
  sample?: Array<{ title: string; url: string; published_at: string; tickers?: string[] }>;
  error_code?: string;
  reason?: string;
};
export async function getNewsSourcesConfig(signal?:AbortSignal):Promise<{push:NewsPushSettings;sources:NewsSource[]}>{
  return await ownerJson("news-sources",{signal},"新闻源配置暂时无法读取。");
}
export async function saveNewsPushSettings(summaryMaxTokens:number):Promise<{ok:boolean;push:{summary_max_tokens:number}}>{
  return await ownerJson("news-sources/push-settings",{method:"PUT",body:{summary_max_tokens:summaryMaxTokens}},"保存失败，请重试。");
}
export async function upsertNewsSource(input:NewsSourceInput):Promise<{ok:boolean;source:NewsSource}>{
  return await ownerJson("news-sources",{method:"POST",body:input},"保存新闻源失败，请检查 ID 和 URL 格式。");
}
export async function setNewsSourceEnabled(sourceId:string,enabled:boolean):Promise<{ok:boolean;enabled:boolean}>{
  return await ownerJson(`news-sources/${encodeURIComponent(sourceId)}/enabled`,{method:"POST",body:{enabled}},"操作失败，请重试。");
}
export async function dryRunNewsSource(sourceId:string):Promise<NewsDryRunResult>{
  return await ownerJson(`news-sources/${encodeURIComponent(sourceId)}/dry-run`,{method:"POST"},"测试抓取失败，请重试。");
}
export async function repairNewsSource(sourceId:string):Promise<{ok:boolean;status?:string;error_code?:string;source?:NewsSource;sample?:Array<{title:string;url:string}>}>{
  return await ownerJson(`news-sources/${encodeURIComponent(sourceId)}/repair`,{method:"POST"},"REA 诊断修复失败，请重试。");
}
export async function deleteNewsSource(sourceId:string):Promise<{ok:boolean}>{
  return await ownerJson(`news-sources/${encodeURIComponent(sourceId)}`,{method:"DELETE"},"删除新闻源失败，请重试。");
}
