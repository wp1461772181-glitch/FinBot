// 角色模板 (stage 4f): the memory page's 用模板起步.  The routes are the plan's (docs/superpowers/plans/2026-11-25-stage4f-role-templates.md, Global Constraints, Routes):
//   GET  /agent-chat/role-templates                             -> { templates, applications, duty_mode }
//   POST /agent-chat/role-templates/{template}/preview          body { bot_id?, leave_out? } -> { will_create, reuse, skip, notes }   (writes nothing)
//   POST /agent-chat/role-templates/{template}/apply            same body -> { application, created, reused, skipped }
//   POST /agent-chat/role-templates/applications/{id}/undo      body { leave_out? } -> { removed, gone }
//
// CONTRACT ASSUMPTIONS (the plan leaves these shapes open; the page is written against them, and every one of them is read defensively, so a different shape degrades to less text, not to a crash):
//  1. Template: { id, label, blurb, memory:[{key,kind,text}], briefs:[{key,name,schedule_kind,schedule_time,timezone,every_value?,every_unit?,instruction,skill_key?}],
//     skills:[{key,name,description,body,output_template,allowed_tools}], usual:[skill key of this template | built-in skill name], notes:[sentence] }.  `notes` are the fixed sentences
//     the server words (the duty-mode one already included or left out by the server); the page shows them as given and does not look at `duty_mode` to word anything.
//  2. Preview / apply lines: `reuse` and `skip` are lists of { key, reason } (a key of the template: memory, brief or skill key; a line about a whole part, such as memory_full, may carry
//     the key "memory" or none).  `will_create` is a list of keys or { key, part? }: the page does not need it (anything ticked and not in reuse/skip is written) and ignores its shape.
//     `reason` is the server's Chinese sentence, shown as given (and through t() when it is one of the fixed ones).
//  3. Apply answer: `application` is the new record (same shape as in the list), `created` is { profile_item_ids, task_ids, skill_ids, usual_added } (the plan's record), `reused` and
//     `skipped` are lists of { key, reason }.
//  4. Undo dialog: each application in the list carries `items: [{ id, part: "memory"|"brief"|"skill"|"usual", text, gone? }]` -- the things it wrote with their CURRENT text (he may have
//     edited it) and `gone: true` for one already deleted.  The plan says the undo list shows current text but names only counts in `still_there`; without `items` the dialog says it
//     cannot list them and takes back everything the application still has (an empty `leave_out`).  `id` is what `leave_out` of the undo body names (the plan: "leave_out?: [ids]").
//     `still_there` is { profile_items, tasks, skills, usual } counts (a missing one is 0).
//  5. Undo answer: { removed, gone }, each a list, a count or an object of those; the page only counts them.
//  6. An application: { id, template, label, bot_id, bot_name, applied_at, undone_at, still_there, items? }.  `label` is the Chinese label (短线 / 定投 / 基金经理); the page translates those three.
//  7. A refusal is 4xx with `detail` a code string (unknown_template, unknown_bot, memory_full, too_many_tasks, ...) or a Chinese reason; templateWriteError words it.  A part that is
//     refused inside a successful apply (memory_full, too_many_tasks) comes back as a `skipped` line, not as an error.
//  8. The built-in skill names in `usual` cannot be left out one by one (the page shows them without a checkbox); an unticked skill of the template is not set as usual.

import { ApiError, agentPath, ownerHeaders } from "./base";
import { templateWriteError } from "../role-templates.mjs";

export type TemplateMemory = { key: string; kind: "preference" | "about_me" | "instruction"; text: string };
export type TemplateBrief = { key: string; name: string; schedule_kind: string; schedule_time: string; timezone: string; every_value?: number | null; every_unit?: string | null; instruction: string; skill_key?: string | null };
export type TemplateSkill = { key: string; name: string; description: string; body: string; output_template: string; allowed_tools: string[] };
export type RoleTemplate = { id: string; label: string; blurb: string; memory: TemplateMemory[]; briefs: TemplateBrief[]; skills: TemplateSkill[]; usual: string[]; notes: string[] };
export type ApplicationItem = { id: string; part: string; text: string; gone: boolean };
export type StillThere = { profile_items?: number; tasks?: number; skills?: number; usual?: number };
export type RoleTemplateApplication = { id: string; template: string; label: string; bot_id: string | null; bot_name: string | null; applied_at: string | null; undone_at: string | null; still_there: StillThere; items?: Array<Partial<ApplicationItem>> };
export type RoleTemplates = { templates: RoleTemplate[]; applications: RoleTemplateApplication[]; duty_mode: string };
/** `bot_id` null is 全局 + 助理; `leave_out` the keys he unticked. */
export type ApplyBody = { bot_id: string | null; leave_out: string[] };
export type ResultLine = { key: string; reason: string };
export type TemplatePreview = { will_create: unknown[]; reuse: ResultLine[]; skip: ResultLine[]; notes: string[] };
export type ApplyResult = { application: RoleTemplateApplication | null; created: { profile_item_ids?: string[]; task_ids?: string[]; skill_ids?: string[]; usual_added?: string[] }; reused: ResultLine[]; skipped: ResultLine[] };
export type UndoResult = { removed: unknown; gone: unknown };

const arr = <T,>(value: unknown): T[] => (Array.isArray(value) ? value as T[] : []);

/** Every template and every application of this owner, and the duty mode the server reads (for information).  Owner only: a guest gets 403. */
export async function getRoleTemplates(signal?: AbortSignal): Promise<RoleTemplates> {
  const response = await fetch(agentPath("role-templates"), { signal, cache: "no-store", headers: ownerHeaders() });
  if (!response.ok) throw new ApiError(response.status === 403 ? "登录个人聊天后才能使用模板。" : "模板暂时无法读取。", response.status);
  const data = await response.json().catch(() => null) as Partial<RoleTemplates> | null;
  if (!data || typeof data !== "object") throw new ApiError("模板暂时无法读取。", response.status);
  return { templates: arr<RoleTemplate>(data.templates), applications: arr<RoleTemplateApplication>(data.applications), duty_mode: typeof data.duty_mode === "string" ? data.duty_mode : "" };
}

async function write<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(agentPath(path), { method: "POST", signal, cache: "no-store", headers: ownerHeaders(true), body: JSON.stringify(body) });
  const payload = await response.json().catch(() => null) as ({ detail?: unknown } & Record<string, unknown>) | null;
  if (!response.ok) throw new ApiError(templateWriteError(response.status, payload?.detail), response.status);
  return (payload ?? {}) as T;
}

/** What applying a template would do (reuse and skip lines, the notes); writes nothing. */
export async function previewRoleTemplate(template: string, body: ApplyBody, signal?: AbortSignal): Promise<TemplatePreview> {
  const data = await write<Partial<TemplatePreview>>(`role-templates/${encodeURIComponent(template)}/preview`, body, signal);
  return { will_create: arr(data.will_create), reuse: arr<ResultLine>(data.reuse), skip: arr<ResultLine>(data.skip), notes: arr<string>(data.notes).map(String) };
}
/** The owner presses 应用: writes the ticked parts as ordinary memory, tasks and skills (nothing new is overwritten or archived). */
export async function applyRoleTemplate(template: string, body: ApplyBody, signal?: AbortSignal): Promise<ApplyResult> {
  const data = await write<Partial<ApplyResult>>(`role-templates/${encodeURIComponent(template)}/apply`, body, signal);
  return { application: data.application ?? null, created: data.created ?? {}, reused: arr<ResultLine>(data.reused), skipped: arr<ResultLine>(data.skipped) };
}
/** Takes back what an application wrote and is still there, except the ids left out. */
export async function undoRoleTemplate(applicationId: string, leaveOut: string[], signal?: AbortSignal): Promise<UndoResult> {
  const data = await write<Partial<UndoResult>>(`role-templates/applications/${encodeURIComponent(applicationId)}/undo`, { leave_out: leaveOut }, signal);
  return { removed: data.removed ?? [], gone: data.gone ?? [] };
}
