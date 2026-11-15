import { ownerJson } from "./owner";

export type PriceLine = { symbol:string; above?:number; below?:number };
export type AgentTask = { id:string; name:string; kind:"brief"|"alerts"; schedule_kind:"daily"|"weekdays"|"hourly"|"every"; schedule_time:string;
  every_value:number|null; every_unit:"hours"|"days"|"weeks"|null; max_runs:number|null; runs_done:number; finished:boolean; timezone:string;
  bot_id:string|null; skill_id:string|null; instruction:string|null; scope:"research_queue"|"symbols"; symbols:string[]; channel:"inbox"|"telegram";
  config:{ filings?:boolean; news?:boolean; price_lines?:PriceLine[] }; enabled:boolean;
  last_run_at:string|null; next_run_at:string|null; last_status:string|null; last_status_label:string|null; last_conversation_id:string|null };
export type AgentTaskInput = Partial<Omit<AgentTask,"skill_id"|"id"|"runs_done"|"finished"|"last_run_at"|"next_run_at"|"last_status"|"last_status_label"|"last_conversation_id">> & {skill_id?:string|null};

export async function listAgentTasks(signal?:AbortSignal,botId?:string):Promise<AgentTask[]>{ return (await ownerJson<{tasks:AgentTask[]}>(botId?`tasks?bot_id=${encodeURIComponent(botId)}`:"tasks",{signal},"任务暂时无法读取。")).tasks; }
export type TaskRun = { id:string; task_id:string; task_name:string; status:string; status_label:string; posted:number; tokens:number; conversation_id:string|null; created_at:string|null };
export async function listTaskRuns(botId:string|undefined,signal?:AbortSignal):Promise<TaskRun[]>{ return (await ownerJson<{runs:TaskRun[]}>(botId?`tasks/runs?bot_id=${encodeURIComponent(botId)}&limit=20`:"tasks/runs?limit=20",{signal},"最近运行暂时无法读取。")).runs; }

export async function createAgentTask(task:AgentTaskInput):Promise<AgentTask>{ return (await ownerJson<{task:AgentTask}>("tasks",{method:"POST",body:task},"保存任务失败。")).task; }
export async function updateAgentTask(id:string,task:AgentTaskInput):Promise<AgentTask>{ return (await ownerJson<{task:AgentTask}>(`tasks/${encodeURIComponent(id)}`,{method:"PATCH",body:task},"保存任务失败。")).task; }
export async function deleteAgentTask(id:string):Promise<void>{ await ownerJson(`tasks/${encodeURIComponent(id)}`,{method:"DELETE"},"删除任务失败。"); }
