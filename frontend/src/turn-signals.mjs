// Everything the avatar needs to know about "what is happening", read off data the chat session already has (design 6.3):
// the phase of the running turn, how many tool calls brought something back, whether the ball is in the user's court,
// whether the backend is unreachable.  Pure (no React, no clock of its own): node --test covers it.  This replaces the
// scattered checks that used to live in the components; nothing here changes the session's state machine.
import { awaitsUser } from "./chat-clarification.mjs";
import { APPROVAL_TTL_MS } from "./approval-ttl.mjs";

/** The phases of a turn the avatar tells apart.  idle: nothing running.  listening: the composer has focus and text.
 * thinking: sent, nothing back yet.  tool: a tool is running.  verify: the evidence check or the repair is running.
 * answer: the answer text is streaming. */
export const PHASES = ["idle", "listening", "thinking", "tool", "verify", "answer"];

const lastOf = list => (Array.isArray(list) && list.length ? list[list.length - 1] : undefined);

/** The node kinds that mean "checking the evidence" (turn-flow.mjs: 证据核验, 修复回答). */
const VERIFY_KINDS = ["verify", "repair"];

/** A tool call that came back with nothing to show: the result says so (an empty data list, a zero count) or is an error.  Those are
 * the same things turn-flow.describeOutput calls 没有匹配记录 / 失败原因; an empty result is just an empty result. */
function emptyResult(result) {
  if (result === null || result === undefined) return true;
  if (typeof result !== "object") return false;
  if (Array.isArray(result.data) && result.data.length === 0) return true;
  if (result.count === 0) return true;
  return typeof result.error_code === "string" && result.error_code !== "";
}

/** Tool calls of a message that finished and brought something back: the aura grows by one unit for each (6.2). */
export function unitsOf(message) {
  if (!message || message.role !== "assistant" || !Array.isArray(message.tool_trace)) return 0;
  return message.tool_trace.filter(call => call && call.status === "complete" && !emptyResult(call.result)).length;
}

/** The running turn's phase, from the streaming transcript (the chat state must be "sending"); null when no turn runs. */
function runningPhase(messages) {
  const last = lastOf(messages);
  if (!last || last.role !== "assistant") return "thinking";
  const running = (Array.isArray(last.trace) ? last.trace : []).filter(node => node && node.status === "running");
  const node = lastOf(running);
  if (node && VERIFY_KINDS.includes(node.kind)) return "verify";
  const tools = Array.isArray(last.tool_trace) ? last.tool_trace : [];
  if (tools.some(call => call && call.status === "running")) return "tool";
  if (String(last.content ?? "").trim()) return "answer";
  return tools.length ? "tool" : "thinking";
}

/**
 * The avatar's signal: `{ phase, units, offline }`.
 * `chatState` is the session state ("sending" while a turn runs); `draft` / `composerFocused` describe the input box;
 * `offline` is whether the backend cannot be reached (see {@link isOffline}).
 */
export function turnSignal({ chatState, messages, draft = "", composerFocused = false, offline = false } = {}) {
  const units = unitsOf(lastOf(messages));
  if (chatState === "sending") return { phase: runningPhase(messages), units, offline: Boolean(offline) };
  const listening = composerFocused && String(draft ?? "").trim() !== "" && !offline;
  return { phase: listening ? "listening" : "idle", units, offline: Boolean(offline) };
}

/** Offline = the backend is unreachable (the connectivity flag, which the app's own requests light: connectivity.mjs) or the last turn
 * failed because the request never got an answer (the session's own `failure.network`).  No probe of its own. */
export function isOffline({ backendDown = false, chatState, messages } = {}) {
  if (backendDown) return true;
  const last = lastOf(messages);
  return chatState === "error" && Boolean(last && last.failure && last.failure.network);
}

/**
 * Is the ball still in the user's court?  The last message waits for them (a waiting status, or a card to answer) and its card has not
 * run out.  `expiresAt` (epoch ms) is when a card made in this tab stops being valid, null when it never does (a card read back from the
 * server has no arrival time, and a waiting status without a card has no clock).  Answering starts a new turn, which supersedes this.
 */
export function awaiting(messages, now) {
  const last = lastOf(messages);
  if (!awaitsUser(last)) return { waiting: false, expiresAt: null };
  const cardAt = last.card_at;
  const expiresAt = last.clarification && typeof cardAt === "number" && Number.isFinite(cardAt) ? cardAt + APPROVAL_TTL_MS : null;
  return { waiting: expiresAt === null || now < expiresAt, expiresAt };
}

/**
 * What the screen-reader status line says (design 6.9: only on a change of phase, one sentence): `{ phrase, detail }` or null (nothing to
 * say).  `phrase` is a Chinese source phrase the caller translates and puts after the bot's name; `detail` (the running tool's name, for
 * the caller to turn into its label) follows it.  The caller keeps the last value and speaks when it changes, never per streamed word.
 */
export function announcement({ phase, waiting = false, offline = false, tool = null } = {}) {
  if (offline) return { phrase: "连接不上服务器", detail: null };
  if (phase === "thinking") return { phrase: "正在思考", detail: null };
  if (phase === "tool") return { phrase: "正在调用工具", detail: typeof tool === "string" && tool ? tool : null };
  if (phase === "verify") return { phrase: "正在核对证据", detail: null };
  if (phase === "answer") return { phrase: "正在作答", detail: null };
  if (waiting) return { phrase: "在等你确认", detail: null };
  return null;
}

/** The name of the tool that is running now (the last one still running in the streaming message), or null. */
export function runningTool(messages) {
  const last = lastOf(messages);
  const calls = last && last.role === "assistant" && Array.isArray(last.tool_trace) ? last.tool_trace.filter(call => call && call.status === "running") : [];
  const name = lastOf(calls)?.name;
  return typeof name === "string" && name ? name : null;
}
