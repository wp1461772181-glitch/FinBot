// The new / edit form of a routine task as plain data: the draft the drawer holds, the body it sends, and the rules that stop it.  Pure, so a node test holds
// it.  The body is what the old form (`TaskManager` of the old BotRoutines.tsx, gone with P7.2) sent for the same input, key for key; the rules are its rules (every one of them is
// listed at once here, the old form stopped at the first).

import { linesToRows, rowProblem, rowsProblems, rowsToLines, sameRows } from "./price-lines.mjs";

export const KINDS = ["brief", "alerts"];
export const SCHEDULES = ["daily", "weekdays", "hourly", "every"];
export const EVERY_UNITS = ["hours", "days", "weeks"];
export const COUNT_MODES = ["unlimited", "once", "count"];
export const SCOPES = ["research_queue", "symbols"];
export const SECTIONS = ["basics", "time", "scope", "content"];
export const MAX_NAME = 80;
export const MAX_SYMBOLS = 30;
export const MAX_PRICE_LINES = 30;
export const DEFAULT_TIMEZONE = "Asia/Shanghai";
/** A stock code as the server takes it (agent_tasks.py `_SYMBOL`, after upper-casing). */
export const SYMBOL = /^[A-Z][A-Z0-9.\-]{0,9}$/;

/** The form of a task nobody has filled in: what the old form opened with. */
export function blankDraft({ botId = "" } = {}) {
  return {
    botId, name: "研究队列简报", kind: "brief",
    schedule: "weekdays", time: "08:00", timezone: DEFAULT_TIMEZONE, everyValue: "1", everyUnit: "days", countMode: "unlimited", runs: "5",
    scope: "research_queue", symbols: [],
    instruction: "", skill: "", filings: true, news: true, priceRows: [], telegram: false,
  };
}

/** The draft of a task being edited (what the old form showed for it).  `fallbackBotId`: the bot a task without one is shown under. */
export function draftFromTask(task, { fallbackBotId = "" } = {}) {
  const blank = blankDraft();
  return {
    botId: task.bot_id ?? fallbackBotId, name: task.name ?? blank.name, kind: task.kind ?? blank.kind,
    schedule: task.schedule_kind ?? blank.schedule, time: task.schedule_time ?? blank.time, timezone: task.timezone ?? blank.timezone,
    everyValue: String(task.every_value ?? 1), everyUnit: task.every_unit ?? "days",
    countMode: task.max_runs ? (task.max_runs === 1 ? "once" : "count") : "unlimited", runs: String(task.max_runs ?? 5),
    scope: task.scope ?? blank.scope, symbols: Array.isArray(task.symbols) ? [...task.symbols] : [],
    instruction: task.instruction ?? "", skill: task.skill_id ?? "",
    filings: task.config?.filings ?? true, news: task.config?.news ?? true, priceRows: linesToRows(task.config?.price_lines ?? []), telegram: task.channel === "telegram",
  };
}

/**
 * Every rule the form has, as [{ field, section, message }] in the order the sections come (an empty list: the form can be sent).  `message` is a Chinese
 * phrase the caller translates; a price-line row is named by its index (`field: "priceRows:2"`, with `problem`).
 */
export function validateDraft(draft) {
  const problems = [];
  const add = (field, section, message, extra = {}) => problems.push({ field, section, message, ...extra });
  if (!draft.name.trim() || draft.name.length > MAX_NAME) add("name", "basics", "请填任务名称（最多 80 字）。");
  if (draft.schedule === "every" && (!Number.isInteger(Number(draft.everyValue)) || Number(draft.everyValue) < 1)) add("everyValue", "time", "间隔要填整数，至少为 1。");
  if (!String(draft.time ?? "").trim()) add("time", "time", "请填运行时间。");
  if (draft.countMode === "count" && (!Number.isInteger(Number(draft.runs)) || Number(draft.runs) < 1)) add("runs", "time", "执行次数要填整数，至少为 1。");
  if (draft.scope === "symbols" && draft.symbols.length === 0) add("symbols", "scope", "股票代码无效，或指定公司时没有填代码。");
  if (draft.kind === "alerts") for (const { index, problem } of rowsProblems(draft.priceRows)) add(`priceRows:${index}`, "content", PRICE_MESSAGES[problem], { index, problem });
  return problems;
}

const PRICE_MESSAGES = {
  raw: "这一行读不出代码和价格。改成「代码 + 高于 / 低于 + 价格」，或删掉这一行。",
  incomplete: "代码和价格都要填。",
  symbol: "代码要以字母开头，最多 10 位（字母、数字、点、短横）。",
  price: "价格要写成数字，如 150 或 150.5。",
};

/** The request body of a task (create and edit alike): the old form's, key for key.  `lockedBotId`: the bot a settings page fixes. */
export function inputFromDraft(draft, { lockedBotId } = {}) {
  const alerts = draft.kind === "alerts";
  return {
    name: draft.name.trim(), kind: draft.kind, schedule_kind: draft.schedule, schedule_time: draft.time, timezone: draft.timezone,
    scope: draft.scope, symbols: draft.scope === "symbols" ? [...draft.symbols] : [],
    every_value: draft.schedule === "every" ? Number(draft.everyValue) : null, every_unit: draft.schedule === "every" ? draft.everyUnit : null,
    max_runs: draft.countMode === "once" ? 1 : draft.countMode === "count" ? Number(draft.runs) : 0,
    channel: alerts && draft.telegram ? "telegram" : "inbox", bot_id: lockedBotId ?? draft.botId,
    instruction: alerts ? null : draft.instruction, skill_id: alerts ? "" : draft.skill,
    config: alerts ? { filings: draft.filings, news: draft.news, price_lines: rowsToLines(draft.priceRows) ?? [] } : {},
  };
}

/** True when the draft differs from the one the drawer opened with (closing it then asks first).  Price rows count by what they say. */
export function draftChanged(draft, initial) {
  const { priceRows, ...rest } = draft, { priceRows: initialRows, ...initialRest } = initial;
  return JSON.stringify(rest) !== JSON.stringify(initialRest) || !sameRows(priceRows, initialRows);
}

/** The first section that has a problem, or null. */
export function firstProblemSection(problems) {
  return SECTIONS.find((section) => problems.some((problem) => problem.section === section)) ?? null;
}

/** Which sections hold a problem (the stepper marks them). */
export function sectionsWithProblems(problems) {
  return SECTIONS.filter((section) => problems.some((problem) => problem.section === section));
}

/** The zone names to choose from: the usual ones first, then every other name the browser knows, and the stored value when it is in neither (it is kept, not changed). */
export const COMMON_ZONES = ["Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore", "Asia/Tokyo", "America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London", "Europe/Paris", "UTC"];
export function timezoneChoices(all, current) {
  const known = Array.isArray(all) ? all.filter((zone) => typeof zone === "string" && zone) : [];
  const pinned = COMMON_ZONES.filter((zone) => known.includes(zone) || zone === "UTC" || zone === DEFAULT_TIMEZONE);
  const rest = known.filter((zone) => !pinned.includes(zone));
  const kept = current && !pinned.includes(current) && !rest.includes(current) ? current : null;
  return { pinned, rest, kept };
}

/** The label of a stored value that is a code with an underscore ("Asia/Hong_Kong" → "Asia/Hong Kong"): readable, the value itself unchanged. */
export function zoneLabel(zone) { return String(zone ?? "").replaceAll("_", " "); }

export { rowProblem };
