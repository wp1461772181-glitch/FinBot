import { ApiError, agentPath, ownerHeaders } from "./base";
import { SKILL_ERRORS, type Skill, type SkillImportPreview, type SkillInput, skillJson } from "./skills-core";

export async function createSkill(input:SkillInput):Promise<Skill>{ return (await skillJson<{skill:Skill}>("skills",{method:"POST",body:input},"保存失败，请重试。")).skill; }
export async function updateSkill(id:string,input:Partial<SkillInput>):Promise<Skill>{ return (await skillJson<{skill:Skill}>(`skills/${encodeURIComponent(id)}`,{method:"PATCH",body:input},"保存失败，请重试。")).skill; }
export async function setSkillEnabled(id:string,enabled:boolean):Promise<Skill>{ return (await skillJson<{skill:Skill}>(`skills/${encodeURIComponent(id)}/enabled`,{method:"POST",body:{enabled}},"操作失败，请重试。")).skill; }
export async function copySkill(id:string):Promise<Skill>{ return (await skillJson<{skill:Skill}>(`skills/${encodeURIComponent(id)}/copy`,{method:"POST"},"复制失败，请重试。")).skill; }
export async function deleteSkill(id:string):Promise<void>{ await skillJson(`skills/${encodeURIComponent(id)}`,{method:"DELETE"},"删除失败，请重试。"); }
export async function exportSkill(id:string):Promise<string>{
  const response=await fetch(agentPath(`skills/${encodeURIComponent(id)}/export`),{cache:"no-store",headers:ownerHeaders()});
  if(!response.ok) throw new ApiError(response.status===404?SKILL_ERRORS.unknown_skill:"导出失败，请重试。",response.status);
  return await response.text();
}
export async function previewSkillImport(markdown:string):Promise<SkillImportPreview>{ return await skillJson("skills/import/preview",{method:"POST",body:{markdown}},"文件无法预览。"); }
export async function importSkill(markdown:string):Promise<Skill>{ return (await skillJson<{skill:Skill}>("skills/import",{method:"POST",body:{markdown}},"导入失败，请重试。")).skill; }
