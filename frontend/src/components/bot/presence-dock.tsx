// The bot standing in the chat header, as ONE avatar that outlives every page of the chat (design 6.7: "the same body becomes another bot").
// The chat page is mounted anew for each bot, so an avatar mounted by the header would be built again on every switch.  This holds it apart:
//   * `PresenceHost` (in the session root, under the chat provider and above the routed pages) renders the avatar by a portal into `dock`, a span that
//     React does not manage the children of (it is created here, once, outside any React tree);
//   * `PresenceSlot` (in the chat header) is an empty span that takes the dock in when it is mounted and gives it back when it goes: DOM moves
//     the dock, React never sees it as a child of anything it could delete.
// When no header exists (another page, a chat with no bot) the dock rests in a detached holder and the avatar is not rendered at all.
import { createPortal } from "react-dom";
import { useLayoutEffect, useRef, useSyncExternalStore, type CSSProperties } from "react";
import { useChat } from "../../app/chat/ChatSessionProvider";
import { BotPresence } from "./BotPresence";

const canDom = typeof document !== "undefined";
const holder = canDom ? document.createDocumentFragment() : null;
const dock = canDom ? document.createElement("span") : null;
if (dock && holder) { dock.setAttribute("data-slot", "presence-dock"); dock.style.display = "contents"; holder.appendChild(dock); }

interface Slot { el: HTMLElement; size: number }
let slot: Slot | null = null;
const listeners = new Set<() => void>();
const setSlot = (next: Slot | null) => { if (slot === next) return; slot = next; listeners.forEach(fn => fn()); };
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

/** Where the avatar stands in the header.  Empty: the avatar arrives inside it. */
export function PresenceSlot({ size, className, style }: { size: number; className?: string; style?: CSSProperties }) {
  const ref = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !dock || !holder) return;
    el.appendChild(dock);
    const mine: Slot = { el, size };
    setSlot(mine);
    // Back to the holder first, then the slot is told it is gone: the dock is never inside a node React is about to remove.
    return () => { if (dock.parentNode === el) holder.appendChild(dock); if (slot === mine) setSlot(null); };
  }, [size]);
  return <span ref={ref} data-slot="presence-slot" className={className} style={style} />;
}

/** The avatar itself: rendered whenever a header offers a slot and a bot's line is open. */
export function PresenceHost() {
  const here = useSyncExternalStore(subscribe, () => slot, () => null);
  const { bot, state, messages, draft, freshExternal, ackExternal } = useChat();
  if (!here || !dock || !bot) return null;
  return createPortal(
    <BotPresence avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={here.size} chatState={state} messages={messages} draft={draft} bot={bot}
      unread={bot.unread > 0 || freshExternal} onAcknowledge={ackExternal} />,
    dock
  );
}
