// A bot's small avatar (tiers XS and S, and the light M / L ones of the settings pages): the body for a bot with a Bloub look, a box with
// the character for an emoji or text avatar. The silhouette and colour come from the bot's stored look; a bot that has none gets its
// preset's recommended look, an old face pick or a hash of its id (bloub-look.resolveLook). `running` / `unread` pick the state.
import { useEffect, useRef, useState } from "react";
import { bloubState, resolveLook } from "../../bloub-look.mjs";
import { parseAvatar } from "../../orb.mjs";
import { bindRowGaze, type RowGazeHandle } from "../../row-gaze.mjs";
import { BotBody } from "./BotBody";

export interface BotAvatarProps {
  avatar: string | null | undefined; look?: unknown; name: string; seed?: string; size?: number;
  running?: boolean; unread?: boolean; frozen?: boolean; className?: string;
  /** A sidebar row's avatar: while the pointer is over the row (`[data-bot-row]`) the eyes follow it. The listeners exist only during the
   * hover and are removed on leave / unmount; touch and reduced motion keep the plain idle avatar. */
  followRow?: boolean;
  rowGaze?: RowGazeHandle;
}

export function BotAvatar({ followRow = false, ...props }: BotAvatarProps) {
  return followRow ? <RowFollowing {...props} /> : <Avatar {...props} />;
}

function Avatar({ avatar, look: stored, name, seed, size = 28, running = false, unread = false, frozen = false, className = "", rowGaze }: BotAvatarProps) {
  const parsed = parseAvatar(avatar, name);
  if (parsed.kind === "text") return <span data-slot="bot-avatar" className={`bot-avatar ${className}`.trim()} aria-hidden="true">{parsed.text}</span>;
  const look = resolveLook(seed || name, avatar, stored, name);
  return <span data-slot="bot-avatar" className={`bot-orb ${className}`.trim()} aria-hidden="true" style={{ width: size, height: size }}>
    <BotBody size={size} shape={look.shape} color={look.color} state={bloubState({ running, unread })} frozenAt={frozen ? 0 : undefined} rowGaze={rowGaze} />
  </span>;
}

function RowFollowing(props: BotAvatarProps) {
  const anchor = useRef<HTMLSpanElement>(null);
  const [handle] = useState<RowGazeHandle>(() => ({ pointer: null }));
  const [active, setActive] = useState(false);
  const followable = parseAvatar(props.avatar, props.name).kind !== "text";
  useEffect(() => {
    const host = anchor.current?.closest("[data-bot-row]");
    if (!followable || !host) return;
    return bindRowGaze(host, { handle, setActive, now: () => performance.now() / 1000, reduced: () => Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) });
  }, [followable, handle]);
  return <span ref={anchor} style={{ display: "contents" }}><Avatar {...props} rowGaze={active ? handle : undefined} /></span>;
}
