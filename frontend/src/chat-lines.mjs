import { AgentChatLifecycle } from "./agentChatLifecycle.js";

const DRAFT_KEY = line => `market-evidence-agent:draft:${line}:v1`;
const defaultStorage = () => { try { return globalThis.localStorage; } catch { return undefined; } };

/** One chat line per bot ("bot:<id>"), per opened conversation ("conv:<id>") or the legacy single line ("local"). */
export function lineKey(bot, conversationId) {
  if (bot?.id) return `bot:${bot.id}`;
  if (conversationId) return `conv:${conversationId}`;
  return "local";
}

export function loadDraft(line, storage = defaultStorage()) {
  try { return storage?.getItem(DRAFT_KEY(line)) ?? ""; } catch { return ""; }
}

export function saveDraft(line, text, storage = defaultStorage()) {
  try { if (text) storage?.setItem(DRAFT_KEY(line), text); else storage?.removeItem(DRAFT_KEY(line)); } catch { /* a full or blocked storage must not break typing */ }
}

const blank = () => ({ messages: [], state: "idle", status: "", conversationId: null, historyHasMore: false, historyBefore: null, restoring: false, draft: "", loaded: false, unseen: false, lifecycle: new AgentChatLifecycle() });

/** Per-line state. Switching the viewed line never aborts another line's request; only that line's own lifecycle does. */
export function createLineStore() {
  const lines = new Map();
  let active = null;
  const get = line => { let s = lines.get(line); if (!s) { s = blank(); lines.set(line, s); } return s; };
  return {
    get,
    update(line, patch) {
      const s = get(line), wasSending = s.state === "sending";
      Object.assign(s, patch);
      if (wasSending && s.state !== "sending" && s.state !== "restoring" && line !== active) s.unseen = true;
      return s;
    },
    setActive(line) { active = line; if (line) get(line).unseen = false; },
    active: () => active,
    all: () => [...lines],
    running: () => [...lines].filter(([, s]) => s.state === "sending").map(([k]) => k),
    unseen: () => [...lines].filter(([, s]) => s.unseen).map(([k]) => k),
    markSeen(line) { get(line).unseen = false; },
  };
}
