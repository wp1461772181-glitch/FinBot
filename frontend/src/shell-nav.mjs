// What the sidebar and the mobile tab bar offer, and where the reader is in it (design 3.1).  Pure: no React, no window.
//
// Six areas: 对话 (the bot list, rendered by the sidebar itself), 研究, 持仓, 任务, 助手, 设置.  The areas with several
// pages (研究, 助手, 设置) carry their sub-pages here, so the old top bar's and tab strips' entries each have one place:
//   研究  自选 (总览) · 预测 · 材料库 · 证据 · 模型成绩 · 历史回放      (the old 公司 / 预测 / 资料库 tabs and the 预测 sub-tabs)
//   助手  全部 bot · 技能 · 记忆 · 新闻源 · 知识库                       (the old 「更多」 items 技能 / 记忆, the rail's 新闻源, the settings page's 研究知识库 button, the 「我」 page)
//   设置  模型 · 通知 · 外观 · 数据 · 账户
// Labels are Chinese phrases: the components pass them through the translation function.
import { pathForSection, paths, sectionOfPath, splitPath } from "./routes.mjs";
import { navGroup } from "./workspace-sections.mjs";

export const AREAS = ["chat", "research", "portfolio", "routines", "assistant", "settings"];

/** Research sub-pages.  `sections` are the old section names an address of the page maps to (the highlight reads them). */
export const RESEARCH_ITEMS = [
  { id: "watchlist", label: "自选", sections: ["overview"] },
  { id: "forecasts", label: "预测", sections: ["forecast", "revisions"] },
  { id: "materials", label: "材料库", sections: ["materials"] },
  { id: "evidence", label: "证据", sections: ["evidence"] },
  { id: "scores", label: "模型成绩", sections: ["evaluation"] },
  { id: "replay", label: "历史回放", sections: ["replay"] },
];
export const ASSISTANT_ITEMS = [
  { id: "bots", label: "全部 bot", owner: true },
  { id: "skills", label: "技能" },
  { id: "memory", label: "记忆" },
  { id: "news", label: "新闻源", owner: true },
  { id: "knowledge", label: "知识库", owner: true },
];
export const SETTINGS_ITEMS = [
  { id: "models", label: "模型" },
  { id: "notifications", label: "通知" },
  { id: "appearance", label: "外观" },
  { id: "data", label: "数据" },
  { id: "account", label: "账户" },
];
/** The assistant pages a guest still sees listed (skills and memory showed in the old 「更多」 menu for guests; the rest were owner-only rows). */
export const GUEST_ASSISTANT_ITEMS = ASSISTANT_ITEMS.filter((item) => !item.owner);

/** Where a research sub-page goes, for a reader looking at `symbol` (the library and evidence pages carry it in the address). */
function researchPath(id, symbol) {
  switch (id) {
    case "watchlist": return paths.research();
    case "forecasts": return pathForSection("forecast", symbol);
    case "materials": return pathForSection("materials", symbol);
    case "evidence": return pathForSection("evidence", symbol);
    case "scores": return pathForSection("evaluation", symbol);
    case "replay": return pathForSection("replay", symbol);
    default: return paths.research();
  }
}

/** The address of an area's own entry, or of one of its sub-pages. */
export function areaPath(area, symbol, itemId) {
  switch (area) {
    case "chat": return itemId === "history" ? paths.chatHistory() : paths.chat();
    case "research": return itemId ? researchPath(itemId, symbol) : paths.research();
    case "portfolio": return paths.portfolio();
    case "routines": return paths.routines();
    case "assistant": return paths.assistant(itemId ?? "bots");
    case "settings": return paths.settings(itemId ?? "models");
    default: return paths.chat();
  }
}

/** The sub-pages an area has. */
export function areaItems(area, { personal = true } = {}) {
  if (area === "research") return RESEARCH_ITEMS;
  if (area === "assistant") return personal ? ASSISTANT_ITEMS : GUEST_ASSISTANT_ITEMS;
  if (area === "settings") return SETTINGS_ITEMS;
  return [];
}

/** Which area an address is in. */
export function activeArea(path) {
  const section = sectionOfPath(path);
  const group = navGroup(section);
  if (group === "chat") return "chat";
  if (group === "portfolio" || group === "routines") return group;
  if (section === "me" || group === "skills" || group === "memory" || group === "news") return "assistant";
  if (section === "knowledge") return "assistant";
  if (group === "settings") return "settings";
  return "research";
}

/** Which sub-page of its area an address is on ("history" for the conversation list), or null. */
export function activeItem(path) {
  const area = activeArea(path), section = sectionOfPath(path);
  const { pathname } = splitPath(path);
  if (area === "chat") return pathname === paths.chatHistory() ? "history" : null;
  if (area === "research") return RESEARCH_ITEMS.find((item) => item.sections.includes(section))?.id ?? null;
  if (area === "assistant") return section === "me" ? "bots" : section;
  if (area === "settings") return section === "knowledge" ? null : (pathname.split("/")[2] ?? "models");
  return null;
}

/** Pages that only the signed-in owner can use: a guest meets the 需要登录 notice there instead of the page. */
export function needsLogin(path) {
  const { pathname } = splitPath(path);
  const parts = pathname.split("/").filter(Boolean);
  const [head, second] = parts;
  if (head === "portfolio" || head === "routines" || head === "assistant") return true;
  // A bot's own line and its settings; /chat, /chat/history and a plain conversation stay readable as a guest.
  if (head === "chat" && second && second !== "history" && second !== "c") return true;
  return false;
}
