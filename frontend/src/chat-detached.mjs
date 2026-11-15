// FP13-c: a turn the server keeps running after this page lets go of it (detached turns).  Pure functions only: no React, no DOM.
// The storage and the reader are handed in by the caller.  Spec: the FP13-c addendum (§3 behaviour, §4 W2 functions), kept outside the repo.

export const STREAM_IDLE_MS = 45000;
export const BACKGROUND_WAIT_MS = 1260000;
const DETACHED_KEY = (cid) => `market-evidence-agent:detached-turn:${cid}:v1`;

/** How a stream that broke ended.  `aborted`: this page stopped it.  `detachable`: the server said it would keep the turn (`: detached` was seen). */
export function streamBreak({ aborted, detachable, sawTerminal, closed }) {
  if (aborted) return "stopped";
  if (detachable && !sawTerminal && closed) return "ended";
  if (detachable && !sawTerminal) return "detached";
  return "failed";
}

/** The next chunk of the body, or `{idle:true}` when the watch is on and nothing came for `idleMs`.  The reader is cancelled then. */
export function nextChunk(reader, { idleMs, watch }) {
  if (!watch) return reader.read();
  let timer;
  const idle = new Promise((resolve) => { timer = setTimeout(() => resolve({ idle: true }), idleMs); });
  return Promise.race([reader.read(), idle]).then(async (result) => {
    clearTimeout(timer);
    if (result && result.idle === true) { await reader.cancel().catch(() => {}); return { idle: true }; }
    return result;
  });
}

/** Keep only whole turns: a turn_id whose group has no assistant line is dropped; messages without a turn_id stay. */
export function completeTurnsOnly(messages) {
  const list = Array.isArray(messages) ? messages : [];
  const answered = new Set();
  for (const m of list) if (m.turn_id && m.role === "assistant") answered.add(m.turn_id);
  return list.filter((m) => !m.turn_id || answered.has(m.turn_id));
}

// The status of a turn's answer line (the last assistant line with that turn_id), or undefined when there is none.
function answerStatus(messages, turnId) {
  let status;
  for (const m of messages ?? []) if (m.role === "assistant" && m.turn_id === turnId) status = m.status ?? "complete";
  return status;
}
// A turn is worth a divider only when it produced an answer: not failed, not stopped.
function answeredAway(messages, turnId) {
  const status = answerStatus(messages, turnId);
  return status !== undefined && status !== "failed" && status !== "cancelled";
}

/** What a poll (or a send-time sync) brought in: the turns this page owns (a divider, away), the others (external), and whether the background turn is over. */
export function arrivalSplit({ arrived, messages, ownTurnId, background }) {
  const away = [], external = [];
  const ownArrived = Boolean(ownTurnId) && (arrived ?? []).includes(ownTurnId);
  for (const id of arrived ?? []) {
    if (id === ownTurnId) { if (answeredAway(messages, id)) away.push(id); continue; }
    external.push(id);
  }
  const clearBackground = Boolean(background) && (background.turnId ? (arrived ?? []).includes(background.turnId) : (arrived ?? []).length > 0);
  return { away, external, clearBackground, ownArrived };
}

export function detachedKey(cid) { return DETACHED_KEY(cid); }

/** The local note: this page has a turn running on the server for this conversation. */
export function saveDetached(storage, cid, record) {
  try { storage?.setItem(detachedKey(cid), JSON.stringify(record)); } catch { /* a full or blocked storage is not an error */ }
}

export function loadDetached(storage, cid) {
  try {
    const raw = storage?.getItem(detachedKey(cid));
    if (!raw) return null;
    const record = JSON.parse(raw);
    if (!record || typeof record !== "object") return null;
    if (typeof record.turnId !== "string" || !Number.isFinite(record.at) || typeof record.question !== "string") return null;
    if (record.gone !== undefined && typeof record.gone !== "boolean") return null;
    return record;
  } catch { return null; }
}

export function dropDetached(storage, cid) {
  try { storage?.removeItem(detachedKey(cid)); } catch { /* ignore */ }
}

/** The server has confirmed the turn is not running, but this page must still count its arrival as its own. */
export function markDetachedGone(storage, cid) {
  const record = loadDetached(storage, cid);
  if (record) saveDetached(storage, cid, { ...record, gone: true });
}

/** What to do on a restore with the note in hand.  `messages` are the restored messages of the conversation. */
export function resumePlan({ marker, messages, now }) {
  if (!marker) return { kind: "none" };
  if ((messages ?? []).some((m) => m.turn_id === marker.turnId)) return { kind: "arrived", turnId: marker.turnId, away: answeredAway(messages, marker.turnId) };
  if (marker.gone) return { kind: "gone" };
  if (now - marker.at > BACKGROUND_WAIT_MS) return { kind: "expired" };
  return { kind: "running", turnId: marker.turnId, question: marker.question, at: marker.at };
}

export function backgroundExpired(background, now) {
  return Boolean(background) && now - background.at > BACKGROUND_WAIT_MS;
}

/** A busy restore puts back the very list that was on screen before the send.  Reference equality is the signal: no turn was produced. */
export function restoredBeforeSend(beforeList, messages) {
  return Boolean(beforeList) && beforeList === messages;
}
