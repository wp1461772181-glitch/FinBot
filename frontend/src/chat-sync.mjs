// Live refresh of an open conversation: turns written from outside this tab (a Telegram message, a reminder, a push)
// are pulled in by polling the newest few turns and appending the ones this tab has not seen.
// Merging is by turn id and append-only, so existing message objects are untouched (no re-render, no reflow), and
// nothing is ever merged into a line that is answering, restoring or testing.  The draft is never read or written here.

const VISIBLE_MS = 4000, HIDDEN_MS = 60000, MAX_BACKOFF_MS = 60000;
const BUSY = new Set(["sending", "testing", "restoring"]);

/** Delay before the next poll: 4 s while the page is visible, 60 s hidden, doubling (capped) after failures. */
export function pollDelay({ hidden = false, failures = 0 } = {}) {
  if (hidden) return HIDDEN_MS;
  return Math.min(VISIBLE_MS * 2 ** Math.max(0, Math.min(failures, 10)), MAX_BACKOFF_MS);
}

/** Turn id of every local message.  A user message sent from this tab has none yet; it takes the id of the answer after it. */
function localTurnIds(messages) {
  const ids = new Array(messages.length);
  let carry;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.turn_id) { ids[i] = m.turn_id; carry = m.turn_id; }
    else if (m.role === "user") { ids[i] = carry; carry = undefined; }
    else ids[i] = undefined;
  }
  return ids;
}

function groupByTurn(messages) {
  const groups = [];
  for (const m of messages) {
    if ((m.role !== "user" && m.role !== "assistant") || !m.turn_id) continue;
    const last = groups.at(-1);
    if (last && last.id === m.turn_id) last.items.push(m);
    else groups.push({ id: m.turn_id, items: [m] });
  }
  return groups;
}

/**
 * @returns {{messages, added: number, gap: boolean}}  `messages` is `local` itself when nothing was added.
 * `gap`: the fetched window shares no turn with the transcript, so the new turns cannot be placed safely.
 */
export function mergeNewTurns(local, serverTail) {
  const ids = localTurnIds(local), known = new Set(ids.filter(Boolean));
  const groups = groupByTurn(serverTail);
  let from = 0;
  if (known.size) {
    const lastKnown = groups.findLastIndex(g => known.has(g.id));
    if (lastKnown < 0) return { messages: local, added: 0, gap: groups.length > 0 };
    from = lastKnown + 1;
  }
  const fresh = groups.slice(from).filter(g => !known.has(g.id));
  if (!fresh.length) return { messages: local, added: 0, gap: false };
  let base = local;
  const tail = local.at(-1);
  if (tail && tail.role === "user" && !ids.at(-1)) {
    const first = fresh[0].items[0];
    if (first.role === "user" && first.content === tail.content) base = local.slice(0, -1);
  }
  return { messages: [...base, ...fresh.flatMap(g => g.items)], added: fresh.length, gap: false };
}

/**
 * Decide what a poll result does to one line.  Null = leave it alone: the line is answering / restoring / testing, or the reply
 * belongs to a different conversation than the line shows now.  Otherwise `{messages, added}`; the caller applies only `messages`.
 */
export function planTailSync(lineState, serverTail, conversationId) {
  if (!lineState || BUSY.has(lineState.state) || lineState.restoring) return null;
  if (!conversationId || lineState.conversationId !== conversationId) return null;
  const { messages, added } = mergeNewTurns(lineState.messages, serverTail);
  return added ? { messages, added } : null;
}
