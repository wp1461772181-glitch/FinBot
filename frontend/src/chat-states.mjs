// What the chat page's state rows need to decide (design 4.2, 对话页的状态), apart from how they look: where an outside message came from, which
// failures send the reader to the settings, what 重试 resends, and which lines finished in the background since the last look.
import { isTaskPostHead, parseTaskPostHead } from "./task-posts.mjs";

/**
 * Where a turn written from outside this tab came from, read off its user row.  The server marks nothing but a routine's result (its row is the
 * task head), so that is the only source that can be named; anything else (Telegram included) is an outside message and says so.
 */
export function externalSource(userContent) {
  if (!isTaskPostHead(userContent)) return { kind: "external", name: null, time: null };
  const head = parseTaskPostHead(userContent);
  return head.name ? { kind: "routine", name: head.name, time: head.time } : { kind: "external", name: null, time: null };
}

/** The turn ids in `after` that `before` did not have: what a poll brought in. */
export function newTurnIds(before, after) {
  const known = new Set((before ?? []).map((message) => message.turn_id).filter(Boolean));
  const fresh = [];
  for (const message of after ?? []) if (message.turn_id && !known.has(message.turn_id) && !fresh.includes(message.turn_id)) fresh.push(message.turn_id);
  return fresh;
}

/** The index of the first message of each turn in `turnIds`: where the 「来自 …」 divider goes. */
export function firstOfTurns(messages, turnIds) {
  const wanted = new Set(turnIds ?? []), seen = new Set(), out = new Map();
  (messages ?? []).forEach((message, index) => { if (message.turn_id && wanted.has(message.turn_id) && !seen.has(message.turn_id)) { seen.add(message.turn_id); out.set(index, message.turn_id); } });
  return out;
}

// The error codes whose way out is a setting: no model, no key, a key the provider refuses, a model the key cannot use.
const SETTINGS_CODES = new Set(["model_not_configured", "model_key_missing", "model_not_found", "provider_invalid_key", "provider_model_access_denied", "provider_model_unavailable_or_invalid_request"]);

/** True when 去设置 helps with this failure. */
export function failureNeedsSettings(code) { return SETTINGS_CODES.has(String(code ?? "").replaceAll('"', "")); }

/**
 * What 重试 does: the turn that failed is taken off the end and its question goes out again, as the same request (a card's answer keeps its
 * request id and label).  `last` is the request the provider sent last; it is used only when it is what the thread's last user line shows.
 * Null when the thread does not end in a failed answer after a user line.
 */
export function retryPlan(messages, last) {
  const list = Array.isArray(messages) ? messages : [];
  const tail = list[list.length - 1];
  if (tail?.role !== "assistant" || tail.status !== "failed") return null;
  let user = -1;
  for (let i = list.length - 2; i >= 0; i -= 1) if (list[i].role === "user") { user = i; break; }
  if (user < 0 || !list[user].content) return null;
  const shown = list[user].content;
  const same = last && (last.label || last.content) === shown;
  return { base: list.slice(0, user), content: same ? last.content : shown, pendingRequestId: same ? last.pendingRequestId : undefined, label: same ? last.label : undefined };
}

/** The keys in `next` that `previous` did not have (lines that just finished while the reader was elsewhere). */
export function newlyListed(previous, next) {
  const had = new Set(previous ?? []);
  return (next ?? []).filter((key) => !had.has(key));
}

/** The bot id a line key names ("bot:<id>"), or null. */
export function botIdOfLine(key) { return typeof key === "string" && key.startsWith("bot:") ? key.slice(4) : null; }
