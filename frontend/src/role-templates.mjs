// 用模板起步 (the memory page's section, stage 4f): pure helpers for the template cards, the preview dialog, the applied list and the undo dialog.  The data is the server's
// (GET /agent-chat/role-templates and the preview / apply / undo answers, see src/api/role-templates.ts); nothing here decides what a template contains or what a write does, it only
// groups, counts and words what the server sent.  Wording that carries a number, a date or a name is made for the locale here; fixed words go through the page's own t().

import { scheduleLabel } from "./inbox-items.mjs";
import { dayLabel } from "./owner-views.mjs";

const list = (value) => (Array.isArray(value) ? value.filter((v) => v && typeof v === "object") : []);
const text = (value) => (typeof value === "string" ? value : "");
const en = (locale) => locale === "en-US";

const LABELS_EN = { 短线: "Short-term", 定投: "DCA", 基金经理: "Fund manager" };
/** A template's label (短线 / 定投 / 基金经理) in the locale; a label that is not one of the three stays as the server sent it. */
export function templateLabel(label, locale = "zh-CN") {
  const clean = text(label).trim();
  return en(locale) ? (LABELS_EN[clean] ?? clean) : clean;
}

const ZONES = { "America/New_York": ["纽约时间", "New York time"], "Asia/Shanghai": ["北京时间", "Beijing time"] };
/** The time zone in plain words; one that is not known is its own name with the underscores undone. */
export function zoneText(zone, locale = "zh-CN") {
  const known = ZONES[zone];
  return known ? known[en(locale) ? 1 : 0] : text(zone).replaceAll("_", " ");
}

/** When a brief runs, in plain words: 「工作日 09:00 · 纽约时间」, 「每 30 天（从 10:00 起）· 北京时间」. */
export function whenText(brief, locale = "zh-CN") {
  return [scheduleLabel(brief ?? {}, locale), zoneText(brief?.timezone, locale)].filter(Boolean).join(" · ");
}

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
function partsLine(memory, briefs, skills, locale) {
  return en(locale)
    ? [plural(memory, "memory item", "memory items"), plural(briefs, "brief", "briefs"), plural(skills, "skill", "skills")].join(" · ")
    : `${memory} 条记忆 · ${briefs} 个简报 · ${skills} 个技能`;
}
/** The count line of a template card: 「3 条记忆 · 1 个简报 · 2 个技能」. */
export function countsLine(template, locale = "zh-CN") {
  return partsLine(list(template?.memory).length, list(template?.briefs).length, list(template?.skills).length, locale);
}

/** The keys of every part of a template, by part and all together (the keys the preview and apply bodies name in `leave_out`). */
export function templateKeys(template) {
  const keys = (rows) => list(rows).map((row) => String(row.key ?? "")).filter(Boolean);
  const memory = keys(template?.memory), briefs = keys(template?.briefs), skills = keys(template?.skills);
  return { memory, briefs, skills, all: [...memory, ...briefs, ...skills] };
}

/** The keys the owner has unticked, in the template's order: the body's `leave_out`.  `ticked` is a Set of keys. */
export function leaveOutOf(template, ticked) {
  return templateKeys(template).all.filter((key) => !ticked.has(key));
}

/** Everything ticked: the dialog's starting state (the owner decided: briefs too, he can untick). */
export function allTicked(template) {
  return new Set(templateKeys(template).all);
}

/** True when at least one part is ticked (an application of nothing is not offered). */
export function anyTicked(template, ticked) {
  return templateKeys(template).all.some((key) => ticked.has(key));
}

/**
 * The usual skills the template would set, from what is ticked: its own skills that are ticked, then the built-in names it names (those cannot be left out one by one).  Each is
 * `{ key, name, builtin }`.  This only says what the server will be asked for; the preview says what it found.
 */
export function usualRows(template, ticked) {
  const skills = new Map(list(template?.skills).map((skill) => [String(skill.key), skill]));
  const rows = [];
  for (const entry of Array.isArray(template?.usual) ? template.usual : []) {
    const key = text(entry);
    if (!key) continue;
    const own = skills.get(key);
    if (own) { if (ticked.has(key)) rows.push({ key, name: text(own.name) || key, builtin: false }); }
    else rows.push({ key, name: key, builtin: true });
  }
  return rows;
}

/** A brief that is ticked while the skill it follows is not: the sentence that says so (the brief's instruction names the skill's steps).  [] when there is none. */
export function skillWarnings(template, ticked, locale = "zh-CN") {
  const skills = new Map(list(template?.skills).map((skill) => [String(skill.key), skill]));
  const out = [];
  for (const brief of list(template?.briefs)) {
    const key = text(brief.skill_key);
    if (!key || !ticked.has(String(brief.key)) || ticked.has(key)) continue;
    const skill = text(skills.get(key)?.name) || key;
    out.push(en(locale)
      ? `The brief "${text(brief.name)}" follows the skill "${skill}", which is not ticked. Unless you already have a skill of that name, the brief runs without its steps.`
      : `简报「${text(brief.name)}」要按技能「${skill}」的步骤做，而这个技能没勾；除非你已有同名技能，简报运行时就没有这些步骤。`);
  }
  return out;
}

/** One line of what the preview found for a key, whatever shape the list holds it in (a bare key or `{ key, reason }`). */
function line(entry) {
  if (typeof entry === "string") return { key: entry, reason: "" };
  if (!entry || typeof entry !== "object") return null;
  const key = String(entry.key ?? "");
  return key || text(entry.reason) ? { key, reason: text(entry.reason) } : null;
}

/** What each key will be, by the preview: a Map key → `{ kind: "reuse" | "skip", reason }`.  A key not in it is written.  Lines without a key (a whole part refused) are not in it. */
export function previewMarks(preview) {
  const marks = new Map();
  for (const [kind, rows] of [["reuse", preview?.reuse], ["skip", preview?.skip]]) {
    for (const row of Array.isArray(rows) ? rows : []) {
      const one = line(row);
      if (one?.key) marks.set(one.key, { kind, reason: one.reason });
    }
  }
  return marks;
}

/** The name of a key in a template (the memory text, the brief or skill name); "" when the template has no such key. */
export function nameOfKey(template, key) {
  for (const row of [...list(template?.memory), ...list(template?.briefs), ...list(template?.skills)]) {
    if (String(row.key) === key) return text(row.text) || text(row.name);
  }
  return "";
}

/** The reuse and skip lines of a preview or an apply answer, each with the name of what it is about: `{ key, name, reason }` (name "" when the line is about a whole part). */
export function resultLines(rows, template) {
  return (Array.isArray(rows) ? rows : []).map(line).filter(Boolean).map((one) => ({ ...one, name: nameOfKey(template, one.key) }));
}

/** How many things a server list holds: a list is its length, a number is itself, an object is the sum of its lists and numbers. */
export function countThings(value) {
  if (Array.isArray(value)) return value.length;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value && typeof value === "object") return Object.values(value).reduce((sum, part) => sum + countThings(part), 0);
  return 0;
}

/** What an apply wrote: 「写入了 3 条记忆、1 个简报、2 个技能」; "" when nothing new was written. */
export function createdLine(created, locale = "zh-CN") {
  // The server lists what it wrote as entries { part, key, label, id }; the record's { profile_item_ids, task_ids, skill_ids } is read too.
  const byPart = (part) => (Array.isArray(created) ? created.filter((entry) => entry?.part === part).length : 0);
  const memory = Array.isArray(created) ? byPart("memory") : countThings(created?.profile_item_ids);
  const briefs = Array.isArray(created) ? byPart("brief") : countThings(created?.task_ids);
  const skills = Array.isArray(created) ? byPart("skill") : countThings(created?.skill_ids);
  if (memory + briefs + skills === 0) return "";
  return partsLine(memory, briefs, skills, locale);
}

const where = (application, locale) => (application?.bot_id ? (text(application.bot_name) || (en(locale) ? "A bot that is gone" : "已删除的 bot")) : (en(locale) ? "Global" : "全局"));
/** An application in the list: 「在用：短线 · 11月26日 · 全局」; one already taken back: 「已撤掉：…」. */
export function applicationLine(application, locale = "zh-CN") {
  const day = dayLabel(application?.applied_at, locale);
  const head = application?.undone_at ? (en(locale) ? "Removed: " : "已撤掉：") : (en(locale) ? "In use: " : "在用：");
  return head + [templateLabel(application?.label, locale), day, where(application, locale)].filter(Boolean).join(" · ");
}

/** The applications still in use, newest first, then those taken back (the server's order is not trusted). */
export function applicationGroups(applications) {
  const newest = (a, b) => String(b.applied_at ?? "").localeCompare(String(a.applied_at ?? ""));
  const all = list(applications);
  return { live: all.filter((a) => !a.undone_at).sort(newest), undone: all.filter((a) => a.undone_at).sort(newest) };
}

/** What of an application is still there, from the server's counts: 「还在：2 条记忆 · 1 个简报 · 2 个技能」, or 「都已不在了」. */
export function stillThereLine(application, locale = "zh-CN") {
  const there = application?.still_there ?? {};
  // The server's keys are memory, brief, skill, usual; profile_items, tasks, skills are read too.
  const memory = countThings(there.memory ?? there.profile_items), briefs = countThings(there.brief ?? there.tasks), skills = countThings(there.skill ?? there.skills);
  if (memory + briefs + skills + countThings(there.usual) === 0) return en(locale) ? "None of it is left" : "都已不在了";
  return (en(locale) ? "Still there: " : "还在：") + partsLine(memory, briefs, skills, locale);
}

const PART_ORDER = ["memory", "brief", "skill", "usual"];
/**
 * The things an application wrote, as the undo dialog lists them: `{ id, part, text, gone }` in the order memory, briefs, skills, usual skills.  `text` is the current text (he may
 * have edited it), a thing that is already gone has `gone: true`.  An application the server sent without the list gives [] (the dialog then says so and takes back all).
 */
export function applicationRows(application) {
  const rank = (part) => { const at = PART_ORDER.indexOf(part); return at < 0 ? PART_ORDER.length : at; };
  return list(application?.items)
    // The server's rows are { part, id, label, there, note }; { text, gone } is read too.
    .map((row) => ({ id: String(row.id ?? ""), part: text(row.part), text: text(row.label) || text(row.text), gone: row.there === false || Boolean(row.gone) }))
    .filter((row) => row.id)
    .sort((a, b) => rank(a.part) - rank(b.part));
}

/** The ids the owner has unticked in the undo dialog: the body's `leave_out`.  Rows already gone are never sent. */
export function undoLeaveOut(rows, ticked) {
  return rows.filter((row) => !row.gone && !ticked.has(row.id)).map((row) => row.id);
}

/** The undo dialog's starting state: every thing still there is ticked. */
export function undoTicked(rows) {
  return new Set(rows.filter((row) => !row.gone).map((row) => row.id));
}

/** What an undo did: 「撤掉了 3 项」 (and 「另有 1 项已经不在了」); "" when both are empty. */
export function removedLine(result, locale = "zh-CN") {
  const removed = countThings(result?.removed), gone = countThings(result?.gone);
  if (en(locale)) return [removed ? `Removed ${removed} ${removed === 1 ? "item" : "items"}` : "", gone ? `${gone} ${gone === 1 ? "item was" : "items were"} already gone` : ""].filter(Boolean).join("; ");
  return [removed ? `撤掉了 ${removed} 项` : "", gone ? `另有 ${gone} 项已经不在了` : ""].filter(Boolean).join("，");
}

/** The body of a preview or apply request: `bot_id` null is 全局 + 助理. */
export function applyBody(botId, leaveOut) {
  return { bot_id: botId ? String(botId) : null, leave_out: Array.isArray(leaveOut) ? leaveOut : [] };
}

const CODES = {
  unknown_template: "没有这个模板。",
  unknown_bot: "这个 bot 已不存在，换一个范围再试。",
  memory_full: "这一层的记忆已满，先删几条或少勾几条。",
  too_many_tasks: "例行任务已到上限，先删掉几个或不勾简报。",
  too_many_skills: "技能已到上限，先删掉几个或少勾几个。",
  application_not_found: "这次应用已不存在。",
};
/** What a refused request says (the server's detail is a code, or a Chinese reason of its own, which is shown as given). */
export function templateWriteError(status, detail) {
  const code = typeof detail === "string" ? detail : (detail && typeof detail === "object" ? text(detail.code) || text(detail.message) || text(detail.reason) : "");
  if (CODES[code]) return CODES[code];
  if (/[一-鿿]/.test(code)) return code;
  if (status === 403 || status === 401) return "登录个人聊天后才能使用模板。";
  if (status === 404) return "这一项已不存在。";
  return "没有成功，请重试。";
}
