import { ApiError, agentPath, ownerHeaders } from "./base";
import { TASK_ERRORS } from "./owner";

// Skills (stage E): recipes — name, one-line description, steps, allowed catalog tools, optional output template; never code.
export type Skill = { id:string; name:string; description:string; body:string; allowed_tools:string[]; output_template:string|null; version:number; enabled:boolean;
  origin:"builtin"|"mine"|"imported"; status:"active"|"draft"; builtin:boolean; updated_at:string|null };
export type SkillInput = { name:string; description:string; body:string; allowed_tools:string[]; output_template?:string|null; enabled?:boolean; save_draft?:boolean };
export type SkillTool = { name:string; level:string };
export type SkillImportPreview = { skill:{ name:string; description:string; body:string; output_template:string|null; allowed_tools:string[] }; tools:Array<{ name:string; level:string; write:boolean }> };
const SKILL_ERRORS:Record<string,string>={...TASK_ERRORS,invalid_name:"名字不能为空，最多 40 字，不能含 / @ #。",unknown_tool:"技能里有工具目录之外的工具，不能保存。",code_not_allowed:"技能只能是文字步骤，不能带代码。",
  invalid_skill_file:"文件格式不对：开头要有 name / description / tools。",name_taken:"已经有同名技能。",invalid_description:"请写一句话说明什么时候用（最多 120 字）。",invalid_body:"请写步骤（最多 6000 字）。",
  invalid_allowed_tools:"至少选一个工具。",too_many_skills:"技能太多了（最多 60 个）。",unknown_skill:"这个技能不存在。"};
async function skillJson<T>(path:string,init:{method?:string;body?:unknown;signal?:AbortSignal},failure:string):Promise<T>{
  const response=await fetch(agentPath(path),{method:init.method??"GET",signal:init.signal,cache:"no-store",headers:ownerHeaders(init.body!==undefined),
    ...(init.body!==undefined?{body:JSON.stringify(init.body)}:{})});
  if(!response.ok){
    const detail=(await response.json().catch(()=>null) as {detail?:unknown}|null)?.detail;
    throw new ApiError(response.status===403||response.status===401?"登录个人聊天后才能使用技能。":(typeof detail==="string"&&SKILL_ERRORS[detail])||(response.status===404?SKILL_ERRORS.unknown_skill:failure),response.status);
  }
  return await response.json() as T;
}
export async function listSkills(signal?:AbortSignal):Promise<{skills:Skill[];tools:SkillTool[]}>{ return await skillJson("skills",{signal},"技能暂时无法读取。"); }

// Shared with the sibling API modules (kept off the declarations so they stay byte-identical to the original).
export { SKILL_ERRORS, skillJson };
