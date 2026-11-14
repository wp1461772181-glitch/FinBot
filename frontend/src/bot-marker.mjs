// The four marks of a bot row in the sidebar (design 3.1, second point).  Each has its own place on the row so they
// can be told apart at a glance:
//   回答中  the avatar's outer ring turns (CSS, the bot's signature colour) and the right slot says so;
//   新回答  a number badge at the far right (the unread count);
//   等你    an amber dot on the avatar's corner (a different shape and place from the ring) and the right slot says so;
//   无      nothing.
// When several hold at once the order of precedence is: 回答中 > 等你 > 新回答 (the number still shows) > 无.
// That order decides the dot and the right-slot word: while the bot is answering it is not "waiting" for anything yet,
// so only the ring and the word 回答中 show; a waiting bot that is not answering shows the dot and 等你.  The unread
// number is independent of both and always shows, except on the bot whose line is open (it is being read).

/** A bot "waits for you" when the server counts something pending for it, or its line (in this session) ends on an open card. */
export function isWaiting(bot, waitingLines = []) {
  return Number(bot?.pending) > 0 || (Array.isArray(waitingLines) && waitingLines.includes(`bot:${bot?.id}`));
}

/** The marks one row shows.  `unread` is the server's unread count plus one for a finished background answer not yet opened. */
export function botMarker({ running = false, waiting = false, unread = 0, active = false } = {}) {
  const count = active ? 0 : Math.max(0, Math.floor(Number(unread) || 0));
  const word = running ? "running" : waiting ? "waiting" : null;
  return { kind: running ? "running" : waiting ? "waiting" : count > 0 ? "unread" : "none", ring: Boolean(running), dot: Boolean(waiting) && !running, word, count };
}

/** The number a row prints: "99+" past 99. */
export function countLabel(count) {
  return count > 99 ? "99+" : String(count);
}
