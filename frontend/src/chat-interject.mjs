// Speaking while the bot works (3c): what the thread does with a message sent during an answer, and with answers that run side by side.
// Pure helpers over the message list; the session (app/chat/ChatSessionProvider.tsx) calls them and holds the streams.
//
// A message made in this tab carries `client_key` (its own name), an answer carries `client_key` and `user_key` (the message it answers).
// A user message sent while a turn was running also carries `delivery`:
//   sending (the request is on its way), received (the server has it), merged (the running answer took it in), separate (it gets its own answer),
//   stopped (it stopped the running answer), queued (its answer waits for a free slot; `queue_ahead` says how many are before it).
// Stored messages carry none of these: the server gives each user message an `id` and each answer a `reply_to` list, and what happened to a
// message is read from those (an answer that lists a message after its own question took it in; a stopped answer's last extra one stopped it).
import { plainChatPreview } from "./chat-thread.mjs";

const QUOTE_LIMIT = 60;
const refsOf = m => [m.id, m.client_key].filter(Boolean);
const isUser = m => m?.role === "user";

/** The list with the owner's message added.  A send during a running turn starts as `sending`; a normal send names the answer it expects. */
export function addUser(messages, { key, content, interject = false, answerKey }) {
  const item = { role: "user", content, client_key: key, ...(interject ? { delivery: "sending" } : {}), ...(answerKey ? { answer_key: answerKey } : {}) };
  return [...messages, item];
}

/** Change one message found by its client key; the list itself when there is none. */
export function patchByKey(messages, key, patch) {
  const at = messages.findIndex(m => m.client_key === key);
  if (at < 0) return messages;
  return messages.map((m, i) => i === at ? { ...m, ...patch } : m);
}

export function removeByKey(messages, key) {
  return messages.some(m => m.client_key === key) ? messages.filter(m => m.client_key !== key) : messages;
}

/** Put the answer in the list: in place when it is there, else right under its message (after any answer already under it), so a later message never pushes it away. */
export function upsertAnswer(messages, userKey, answer) {
  const at = messages.findIndex(m => m.role === "assistant" && m.client_key === answer.client_key);
  if (at >= 0) return messages.map((m, i) => i === at ? answer : m);
  const owner = messages.findIndex(m => isUser(m) && m.client_key === userKey);
  if (owner < 0) return [...messages, answer];
  let place = owner + 1;
  const takenIn = m => isUser(m) && m.delivery === "merged" && Boolean(answer.turn_id) && m.into_turn === answer.turn_id;
  while (place < messages.length && (messages[place].role === "assistant" || takenIn(messages[place]))) place += 1;
  return [...messages.slice(0, place), answer, ...messages.slice(place)];
}

/**
 * The message that was taken into a running answer goes where it arrived: above that answer (the stored order), so what is last in the list is still the
 * answer (a card on it stays answerable).  The answer may not exist yet: then right under the message it was merged into, and the answer goes below it later.
 */
export function moveMerged(messages, key, { intoTurn, targetUserKey }) {
  const at = messages.findIndex(m => m.client_key === key);
  if (at < 0) return messages;
  const rest = messages.filter((_, i) => i !== at), moved = messages[at];
  const answerAt = intoTurn ? rest.findIndex(m => m.role === "assistant" && m.turn_id === intoTurn) : -1;
  if (answerAt >= 0) return [...rest.slice(0, answerAt), moved, ...rest.slice(answerAt)];
  const owner = rest.findIndex(m => isUser(m) && m.client_key === targetUserKey);
  if (owner < 0) return messages;
  let place = owner + 1;
  while (place < rest.length && isUser(rest[place]) && rest[place].delivery === "merged" && rest[place].into_turn === intoTurn) place += 1;
  return [...rest.slice(0, place), moved, ...rest.slice(place)];
}

/** An answer that will not be written after all (the server turned out to have taken the message in, or the request broke): it goes, and its message stops waiting for it. */
export function withdrawAnswer(messages, userKey, answerKey) {
  return removeByKey(patchByKey(messages, userKey, { answer_key: undefined }), answerKey);
}

/** What an answer answers, as `[{id, text}]`: the server's list when it has one, else what this tab knows (its own message, the ones it took in, the one that stopped it). */
export function replyEntries(messages, index) {
  const m = messages[index];
  if (m?.role !== "assistant") return [];
  if (Array.isArray(m.reply_to) && m.reply_to.length) return m.reply_to;
  if (!m.user_key) return [];
  const ownAt = messages.findIndex(u => isUser(u) && u.client_key === m.user_key);
  if (ownAt < 0) return [];
  const at = [ownAt];
  if (m.turn_id) messages.forEach((u, i) => { if (isUser(u) && u.delivery === "merged" && u.into_turn === m.turn_id) at.push(i); });
  if (m.stopped_by_message) { const stopper = messages.findIndex((u, i) => i > ownAt && isUser(u) && u.delivery === "stopped"); if (stopper >= 0) at.push(stopper); }
  return [...new Set(at)].sort((a, b) => a - b).map(i => ({ id: messages[i].id ?? messages[i].client_key, text: plainChatPreview(messages[i].content, QUOTE_LIMIT) }));
}

/** The one line 「回复：…」 under an answer: only when it is not directly below the one message it answers, or answers more than one.  Null otherwise. */
export function replyQuote(messages, index) {
  const entries = replyEntries(messages, index);
  if (!entries.length) return null;
  if (entries.length === 1) {
    const before = messages[index - 1];
    if (isUser(before) && refsOf(before).includes(entries[0].id)) return null;
  }
  const text = entries.map(e => e.text).filter(Boolean).join(" / ");
  return text || null;
}

/**
 * What happened to each user message, parallel to the list: `{kind, ahead?}` or null.  A message made in this tab says it itself; one read back from
 * the server is judged by the answers that list it.
 */
export function deliveries(messages) {
  const derived = new Map();
  for (const m of messages) {
    if (m.role !== "assistant" || !Array.isArray(m.reply_to) || m.reply_to.length < 2) continue;
    const stoppedHere = m.status === "cancelled" || m.status === "stopped";
    m.reply_to.forEach((entry, at) => { if (at > 0) derived.set(entry.id, stoppedHere && at === m.reply_to.length - 1 ? "stopped" : "merged"); });
  }
  return messages.map(m => {
    if (!isUser(m)) return null;
    if (m.queue_ahead > 0) return { kind: "queued", ahead: m.queue_ahead };
    if (m.delivery === "separate") {
      const own = messages.find(a => a.role === "assistant" && a.client_key && a.client_key === m.answer_key);
      return own && !own.live ? null : { kind: "separate" };
    }
    if (m.delivery) return { kind: m.delivery };
    const kind = m.id ? derived.get(m.id) : undefined;
    return kind ? { kind } : null;
  });
}

/** The indexes of user messages that will have their own answer but do not yet (the thread shows the 「回答中」 placeholder under them). */
export function awaitingAnswer(messages, sending) {
  const waiting = new Set();
  if (!sending) return waiting;
  messages.forEach((m, i) => {
    if (isUser(m) && m.answer_key && !messages.some(a => a.role === "assistant" && a.client_key === m.answer_key)) waiting.add(i);
  });
  return waiting;
}

/** The open requests of each line.  A request is `{key, main, answer, dead, controller}`; `answer` says it is writing (or will write) an answer of its own. */
export function createStreamSet() {
  const lines = new Map();
  const of = line => lines.get(line) ?? [];
  return {
    add(line, handle) { lines.set(line, [...of(line), handle]); },
    remove(line, handle) { const rest = of(line).filter(h => h !== handle); if (rest.length) lines.set(line, rest); else lines.delete(line); },
    all: of,
    count: line => of(line).length,
    /** The newest request that is writing an answer and has not been stopped: what the stop button stops. */
    stopTarget(line) { return of(line).findLast(h => h.answer && !h.dead) ?? null; },
    /** Every request of the line but the main one (the line's own abort handles that one): the line was cleared or another conversation opened. */
    killExtras(line) { for (const h of of(line)) if (!h.main && !h.dead) { h.dead = true; h.controller?.abort(); } },
  };
}

/** 「排队中（前面 N 件）」: how many pieces of work are before it. */
export function queuedText(ahead, locale) {
  return locale === "en-US" ? `Queued (${ahead} ahead)` : `排队中（前面 ${ahead} 件）`;
}
