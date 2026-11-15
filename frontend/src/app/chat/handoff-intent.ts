// The reader asked to switch bot (design 6.7).  This is the one piece of the handoff that runs at the moment of the click, before React has
// even started to render the new line, so it is kept small and synchronous:
//   * the composer of the line being left is made unwritable at once (readonly, and its onChange drops what arrives): between the click and the
//     moment the new line is mounted (A3 measured about 15 ms) whatever was typed used to land in the OLD line's draft;
//   (A picture of the old thread to fade out over the new one was tried: copying even only the messages on screen cost about 35 ms inside the click, on
//   a switch that otherwise takes 160: the new line is mounted at once and the old one is simply gone.  Content does not wait for animation.)
//   * the intent (when, from where, which way) is remembered for the avatar (its handoff clock starts at the click), the thread (how it comes in)
//     and the composer (whether it takes the focus).
// The new line's composer calls `landHandoff` when it is mounted: from then on input is accepted again, into the new line.
import { HANDOFF, movesFocus, type HandoffSource } from "../../handoff.mjs";

export interface Intent {
  id: number; to: string; at: number; source: HandoffSource; dir: -1 | 0 | 1;
  /** The line was mounted (its composer exists): input is accepted again. */
  landed: boolean;
  /** The line has taken its entrance (it plays once), and the composer its focus (once). */
  entered: boolean; focusTaken: boolean;
  /** The signature colour of the line that was left, for the colour to travel from. */
  fromColor: string | null;
}

const nowSec = () => performance.now() / 1000;
let seq = 0, current: Intent | null = null, activeBot: string | null = null, unblock = 0;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(fn => fn());

export function subscribeIntent(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }

/** The intent that asked for `botKey`'s line, while it is fresh (the avatar and the thread read it); null when the line was reached any other way. */
export function currentIntent(botKey?: string | null, maxAge = 2): Intent | null {
  if (!current || nowSec() - current.at > maxAge) return null;
  return botKey == null || current.to === botKey.toLowerCase() ? current : null;
}

/** Composer: is typing refused right now (a switch was asked for and the new line is not there yet)? */
export const inputBlocked = () => Boolean(current && !current.landed && nowSec() - current.at < 1.5);

function setReadonly(on: boolean) {
  const box = document.getElementById("agent-draft");
  if (!box) return;
  if (on) { box.setAttribute("readonly", ""); box.setAttribute("data-handoff", "pending"); } else { box.removeAttribute("readonly"); box.removeAttribute("data-handoff"); }
}

/** The entrance code (handoff-entry.ts) is a chunk of its own, fetched shortly after the first paint; null until it has arrived. */
let entryTools: typeof import("./handoff-entry") | null = null;
if (typeof window !== "undefined") window.setTimeout(() => { void import("./handoff-entry").then(module => { entryTools = module; }).catch(() => undefined); }, 500);
export const loadedEntry = () => entryTools;

export interface BeginOptions { to: string; source: HandoffSource; dir?: -1 | 0 | 1 }

/** Call from the click (or the address change) that switches to bot `to`.  Returns the intent, or null when nothing is switching (the same bot). */
export function beginHandoff({ to, source, dir = 0 }: BeginOptions): Intent | null {
  const target = to.toLowerCase();
  if (target === activeBot) return null;
  if (current && !current.landed && current.to === target && nowSec() - current.at < HANDOFF.RAPID) return current; // the click and the address change it causes
  const at = nowSec();
  const page = document.querySelector<HTMLElement>("[data-slot=chat-page]");
  const intent: Intent = { id: ++seq, to: target, at, source, dir, landed: false, entered: false, focusTaken: false, fromColor: page?.dataset.botColor ?? null };
  current = intent;
  setReadonly(true);
  window.clearTimeout(unblock);
  unblock = window.setTimeout(() => { if (current === intent && !intent.landed) setReadonly(false); }, 1500);
  notify();
  return intent;
}

/** The new line's composer is mounted (and now owns the keyboard). */
export function landHandoff(botKey: string | null) {
  activeBot = botKey ? botKey.toLowerCase() : null; // the bot whose line is on screen
  if (current && !current.landed && (botKey === null || current.to === botKey.toLowerCase())) { current.landed = true; window.clearTimeout(unblock); }
}

/** Each part of the new line takes what it needs of the intent once: the thread its entrance, the composer its focus (only after a switch made with the pointer
 * or the drawer: somebody walking the sidebar with the keyboard keeps the focus on the row, and an address change moves nothing). */
const take = (botKey: string | null, flag: "entered" | "focusTaken") => { const intent = currentIntent(botKey, 1.5); if (!intent || intent[flag]) return null; intent[flag] = true; return intent; };
export const takeEntry = (botKey: string | null) => take(botKey, "entered");
export const takeFocus = (botKey: string | null) => (movesFocus(currentIntent(botKey, 1.5)?.source) ? take(botKey, "focusTaken") : null);

