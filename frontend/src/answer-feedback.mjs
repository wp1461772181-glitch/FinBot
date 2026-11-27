// 「好／不好」 under an answer (5d-3a): what the thumbs show and send.  Pure: no React, no fetch; the browser's storage is passed in.
//
// The owner's verdict lives on the server (PUT / DELETE /agent-chat/conversations/{cid}/turns/{tid}/feedback): the history hands it on
// each answer (`feedback`).  A guest's thumbs stay a note in this browser, under the old key.  The owner's old notes in this browser are
// sent once for the answers shown that have none on the server, then the key is removed.

/** The browser's old note of one turn (up | down), as before 5d-3a. */
export const LOCAL_PREFIX = "market-evidence-agent:feedback:";
export const VERDICTS = ["good", "bad"];
export const THUMBS = [{ verdict: "good", label: "有帮助" }, { verdict: "bad", label: "没有帮助" }];
export const REASON_MAX = 200;
export const REASON_PLACEHOLDER = "哪里不好？（可不填）";
export const FAILED_TEXT = "没记上，请再试一次";
const OLD_VALUES = { up: "good", down: "bad" };

export const localKey = (turnId) => `${LOCAL_PREFIX}${turnId}`;

/** The old note as a verdict (up → good, down → bad); null for none or anything else. */
export function localVerdict(value) {
  return OLD_VALUES[value] ?? null;
}

/** What `storage` (localStorage) holds for a turn, as a verdict; null when it holds nothing or cannot be read. */
export function readLocal(storage, turnId) {
  if (!turnId) return null;
  try { return localVerdict(storage?.getItem(localKey(turnId))); } catch { return null; }
}

/** The verdict the server gave on this answer; null for none (or a value that is not one). */
export function serverVerdict(message) {
  const verdict = message?.feedback?.verdict;
  return VERDICTS.includes(verdict) ? verdict : null;
}

/** What one press does: the same thumb again takes the verdict back (null), the other one replaces it. */
export function nextVerdict(current, pressed) {
  return current === pressed ? null : pressed;
}

/** Whether pressing opens the reason field: only a 不好 that is now being given (not taken back). */
export function asksReason(current, pressed) {
  return pressed === "bad" && current !== "bad";
}

/** The reason as sent: one line, at most 200 characters; null for none. */
export function cleanReason(text) {
  const line = String(text ?? "").split(/\s+/).filter(Boolean).join(" ").slice(0, REASON_MAX);
  return line || null;
}

/** The body of the PUT: the verdict, and the reason only with 不好. */
export function feedbackBody(verdict, reason) {
  const said = verdict === "bad" ? cleanReason(reason) : null;
  return said ? { verdict, reason: said } : { verdict };
}

/**
 * The old note of this answer to send once: the verdict, when the owner's answer is stored on the server (it has an id and a turn id), the server
 * has no verdict on it, and this browser has one.  Null otherwise (then nothing is sent and the key, if any, is left alone).
 */
export function uploadFor(message, storage) {
  if (message?.role !== "assistant" || !message?.id || !message?.turn_id || serverVerdict(message)) return null;
  return readLocal(storage, message.turn_id);
}

/** Remove the old note of a turn once the server has it (a storage that cannot be written is left as it is). */
export function forgetLocal(storage, turnId) {
  try { storage?.removeItem(localKey(turnId)); } catch { /* the note is only a convenience */ }
}

/** A guest's press: toggle the old note (the same thumb twice removes it).  Returns the verdict now kept. */
export function toggleLocal(storage, turnId, pressed) {
  const now = nextVerdict(readLocal(storage, turnId), pressed);
  try {
    if (now === null) storage?.removeItem(localKey(turnId));
    else storage?.setItem(localKey(turnId), now === "good" ? "up" : "down");
  } catch { /* the thumbs are a local note, not required */ }
  return now;
}
