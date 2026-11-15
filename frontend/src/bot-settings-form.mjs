// The bot settings page's form logic (P5.1), pure: what a draft is made of, what a save sends, what counts as a change, which section a change
// belongs to, how the tool list is grouped, which step the Telegram binding is on.  The old 档案 tab kept this in BotSidePanel.tsx (`draftOf`,
// `fieldsOf`); the rules are the same ones, moved here so a node test can hold them.
import { lookForSave, normalizeLook } from "./bloub-look.mjs";

/** The nine sections, in the page's order.  `save` says how a section's changes reach the server: with the save bar, at once, or (危险区) as its own act. */
export const SECTIONS = [
  { id: "profile", label: "档案", save: "bar" },
  { id: "focus", label: "关注", save: "bar" },
  { id: "look", label: "外观与性格", save: "bar" },
  { id: "model", label: "模型", save: "bar" },
  { id: "tools", label: "工具", save: "bar" },
  { id: "skills", label: "技能", save: "live" },
  { id: "routines", label: "例行任务", save: "live" },
  { id: "notify", label: "通知", save: "bar" },
  { id: "danger", label: "危险区", save: "now" },
];
export const DEFAULT_SECTION = "profile";

/** Which fields of a save belong to which section (the unsaved-change dot of a collapsed section on a phone reads this). */
export const SECTION_OF_FIELD = {
  name: "profile", title: "profile", description: "profile", group: "profile", pinned: "profile", hidden: "profile",
  focus: "focus", avatar: "look", look: "look", model: "model", reasoning_effort: "model", tool_scope: "tools", daily_notify_cap: "notify",
};

/** The section an address asks for (`?section=tools`), else the first. */
export function sectionFromSearch(search) {
  const id = new URLSearchParams(String(search ?? "")).get("section");
  return SECTIONS.some((section) => section.id === id) ? id : DEFAULT_SECTION;
}

/** The form's state for a bot as the server has it. */
export function draftOf(bot) {
  return {
    name: bot.name, title: bot.title, description: bot.description, focus: bot.focus, tool_scope: bot.tool_scope, model: bot.model,
    reasoning_effort: bot.reasoning_effort ?? null, template: bot.template, avatar: bot.avatar, look: normalizeLook(bot.look), seed: bot.id,
    group: bot.group, pinned: bot.pinned, hidden: bot.hidden, daily_notify_cap: bot.daily_notify_cap,
  };
}

const sameSymbols = (a, b) => Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((company, index) => company.symbol === b[index].symbol);

/**
 * The body of a save: the whole field set every time (as the old form sent it), with two exceptions.  `look` goes only when it differs from what the
 * server holds (a look picked and picked back is not sent); `reasoning_effort` goes only when it was changed here (the old form had no such field, so a
 * save that does not touch it sends what it always sent).  Choosing 默认 for the effort sends null.
 */
export function fieldsToSave(draft, bot) {
  const look = lookForSave(draft.look, bot?.look);
  const effort = draft.reasoning_effort ?? null;
  const effortChanged = effort !== (bot?.reasoning_effort ?? null);
  return {
    ...(look ? { look } : {}),
    name: draft.name.trim(), title: draft.title.trim(), description: draft.description,
    focus: { companies: sameSymbols(draft.focus.companies, bot?.focus?.companies) ? bot.focus.companies : draft.focus.companies, theme: draft.focus.theme?.trim() || null },
    tool_scope: draft.tool_scope, model: draft.model, ...(effortChanged ? { reasoning_effort: effort } : {}),
    avatar: (draft.avatar ?? "").trim(), group: (draft.group ?? "").trim(), pinned: Boolean(draft.pinned),
    ...(draft.hidden !== undefined ? { hidden: draft.hidden } : {}),
    ...(draft.daily_notify_cap !== undefined ? { daily_notify_cap: draft.daily_notify_cap } : {}),
    template: draft.template,
  };
}

/** The fields a draft changes against the server's bot (the saved shape: trimmed names, `look` and `reasoning_effort` as above). */
export function changedFields(draft, bot) {
  const base = fieldsToSave(draftOf(bot), bot), now = fieldsToSave(draft, bot), changed = [];
  for (const key of Object.keys(now)) {
    if (key === "template") continue;
    if (key === "look" || key === "reasoning_effort" || JSON.stringify(now[key]) !== JSON.stringify(base[key])) changed.push(key);
  }
  return changed;
}
export const hasChanges = (draft, bot) => changedFields(draft, bot).length > 0;
/** The sections that hold a change, as a set of section ids. */
export function sectionsChanged(draft, bot) {
  return new Set(changedFields(draft, bot).map((field) => SECTION_OF_FIELD[field]).filter(Boolean));
}

/** What stops a save, by field: the message is a phrase of the catalog (the page shows it under the field). */
export function validate(draft) {
  const errors = {};
  if (!draft.name.trim()) errors.name = "名字不能为空。";
  return errors;
}

// --- 关注: the companies are tags; the draft keeps the server's objects until the list is changed ------------------------------------
export const focusSymbols = (draft) => draft.focus.companies.map((company) => company.symbol);
/** A new list of symbols: when it is the list the draft already has, the draft itself; else `{symbol}` for each (the old form re-parsed the text the same way).  A list that is the server's again goes out as the server's records (fieldsToSave), so adding a company and taking it back is no change. */
export function withFocusSymbols(draft, symbols) {
  const now = focusSymbols(draft);
  if (symbols.length === now.length && symbols.every((symbol, index) => symbol === now[index])) return draft;
  return { ...draft, focus: { ...draft.focus, companies: symbols.map((symbol) => ({ symbol })) } };
}
export const withFocusTheme = (draft, theme) => ({ ...draft, focus: { ...draft.focus, theme: theme || null } });

// --- 工具: groups ---------------------------------------------------------------------------------------------------------------
/** The tool list's `level` has no network value (read, reversible, costly, card, client, notify, skill): the two read-level tools that go out to the web are named here. */
const WEB_TOOLS = new Set(["web_research", "search_configured_news"]);
export const TOOL_GROUPS = [
  { id: "read", label: "读取类" },
  { id: "web", label: "联网类" },
  { id: "write", label: "写入类 · 需确认" },
  { id: "other", label: "对话与通知" },
];
export function toolGroup(tool) {
  if (tool.level === "read") return WEB_TOOLS.has(tool.name) ? "web" : "read";
  if (tool.level === "reversible" || tool.level === "costly" || tool.level === "write") return "write"; // (`write` is what the old fake lists and the old grid called every non-read level)
  return "other";
}
/** The tools by group, in the order of TOOL_GROUPS, a group with none left out. */
export function groupTools(tools) {
  const list = Array.isArray(tools) ? tools : [];
  return TOOL_GROUPS.map((group) => ({ ...group, tools: list.filter((tool) => toolGroup(tool) === group.id) })).filter((group) => group.tools.length > 0);
}
/** The scope as the heading says it: every tool, or `n / total`. */
export function scopeSummary(scope, total) {
  return scope === null || scope === undefined ? { all: true, count: total, total } : { all: false, count: scope.length, total };
}

// --- 通知: the three steps of a bot's own Telegram ------------------------------------------------------------------------------
export const TELEGRAM_STEPS = ["保存 token", "生成绑定码", "等待绑定"];
/** The step the binding is on, 0 to 3: 0 no token yet, 1 token saved (a code can be made), 2 code made (waiting for the message), 3 bound.  `bind` is the code just made, if any. */
export function telegramStep(state, bind) {
  if (state?.bound) return 3;
  if (!state?.has_token) return 0;
  return bind ? 2 : 1;
}
