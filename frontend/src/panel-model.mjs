// The chat page's right panel (design 4.2): which tabs it has, which round of the conversation it is showing, and how wide it is.
// Pure functions only; the component keeps the state and reads the storage.
import { citationsToShow } from "./chat-citations.mjs";

export const PANEL_TABS = ["sources", "process", "workspace", "profile"];
export const PANEL_MIN = 300;
export const PANEL_MAX = 720;
export const PANEL_DEFAULT = 360;
/** The thread (with its question rail) keeps at least this much of the page next to the panel. */
export const THREAD_MIN = 420;
export const PANEL_KEY_STEP = 16;

/** The tabs a page can show: a bot's page has the workspace and the profile, a conversation with no bot has only sources and process. */
export function availableTabs({ hasWorkspace, hasProfile } = {}) {
  return PANEL_TABS.filter((tab) => (tab === "workspace" ? Boolean(hasWorkspace) : tab === "profile" ? Boolean(hasProfile) : true));
}

/** The tab to show first: the stored one when this page has it, else 工作区 on a bot's page and 来源 elsewhere. */
export function initialTab(stored, available) {
  const tabs = Array.isArray(available) && available.length ? available : availableTabs();
  if (typeof stored === "string" && tabs.includes(stored) && stored !== "profile") return stored;
  return tabs.includes("workspace") ? "workspace" : "sources";
}

/** Width in pixels, a whole number inside [PANEL_MIN, PANEL_MAX] and, when the page width is known, leaving THREAD_MIN for the thread. */
export function clampPanelWidth(value, available) {
  const number = typeof value === "number" && Number.isFinite(value) ? Math.round(value) : PANEL_DEFAULT;
  const room = typeof available === "number" && Number.isFinite(available) && available > 0 ? Math.max(PANEL_MIN, available - THREAD_MIN) : PANEL_MAX;
  return Math.min(Math.min(PANEL_MAX, room), Math.max(PANEL_MIN, number));
}

/** What the storage holds (a string or nothing) as a width. */
export function storedPanelWidth(raw, available) {
  const number = typeof raw === "string" && /^\d{2,4}$/.test(raw.trim()) ? Number(raw) : PANEL_DEFAULT;
  return clampPanelWidth(number, available);
}

/** A round is the bot's answer plus the question before it.  Its key is the turn id the server issued, else its place in the list. */
export function turnKey(message, index) {
  return message && typeof message.turn_id === "string" && message.turn_id ? message.turn_id : `#${index}`;
}

/** Whether an answer has anything for the panel to show: text, a trace, citations or a recorded time. */
export function hasRoundContent(message) {
  if (!message || message.role !== "assistant") return false;
  return Boolean(message.content) || (Array.isArray(message.trace) && message.trace.length > 0) || (Array.isArray(message.citations) && message.citations.length > 0)
    || typeof message.thinking_ms === "number" || (Array.isArray(message.tool_trace) && message.tool_trace.length > 0);
}

/** The index of the round the panel shows: the selected key if it is still in the list, else the newest answer with content (-1 when none). */
export function selectedIndex(messages, key) {
  const list = Array.isArray(messages) ? messages : [];
  if (key) {
    const found = list.findIndex((message, index) => message && message.role === "assistant" && turnKey(message, index) === key);
    if (found >= 0) return found;
  }
  for (let index = list.length - 1; index >= 0; index -= 1) if (hasRoundContent(list[index])) return index;
  return -1;
}

/** The question a round answers: the user message just before the answer, cut to `max` characters. */
export function roundQuestion(messages, index, max = 24) {
  const list = Array.isArray(messages) ? messages : [];
  for (let at = index - 1; at >= 0; at -= 1) {
    const message = list[at];
    if (message && message.role === "user") {
      const text = String(message.content ?? "").replace(/\s+/g, " ").trim();
      return text.length > max ? `${text.slice(0, max)}…` : text;
    }
    if (message && message.role === "assistant") break;
  }
  return "";
}

/** The sources an answer lists, exactly as the old drawer listed them (the protocol decides which). */
export function roundSources(message) {
  return citationsToShow(message?.citation_protocol, message?.citations, message?.citation_nodes);
}
