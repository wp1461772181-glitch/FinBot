// How long a write confirmation lives.  Its own tiny module so the avatar's signals can read it without pulling in the whole card logic.
/** A write confirmation lives ten minutes on the server (design 4.2); the card counts the same time down for a card made in this session. */
export const APPROVAL_TTL_MS = 10 * 60 * 1000;
