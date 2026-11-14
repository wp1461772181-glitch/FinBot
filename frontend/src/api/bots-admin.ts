import { type Bot, type BotFields, type BotTemplate, type BotTool, botJson } from "./bots";

export async function getBotTemplates(signal?:AbortSignal):Promise<{templates:BotTemplate[];tools:BotTool[];always_on:string[]}>{ return await botJson("bot-templates",{signal},"模板暂时无法读取。"); }
export async function createBot(fields:BotFields):Promise<Bot>{ return (await botJson<{bot:Bot}>("bots",{method:"POST",body:fields},"创建失败，请重试。")).bot; }

export async function deleteBot(id:string):Promise<void>{ await botJson(`bots/${encodeURIComponent(id)}`,{method:"DELETE"},"删除失败，请重试。"); }
