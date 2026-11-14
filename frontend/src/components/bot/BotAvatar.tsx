// A bot's small avatar (tiers XS and S, and the light M / L ones of the settings pages): the body for a bot with a Bloub look, a box with
// the character for an emoji or text avatar. The silhouette and colour come from the bot's stored look; a bot that has none gets its
// preset's recommended look, an old face pick or a hash of its id (bloub-look.resolveLook). `running` / `unread` pick the body's pose.
// `status` (S tier, A3) draws the one status mark that every list of bots shares, in CSS around the avatar: a turning ring while the bot is
// answering, an amber dot on the corner while it waits for you; unread and idle draw nothing here (the number is the row's).  It works the
// same for an emoji or a text avatar.
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { bloubState, resolveLook } from "../../bloub-look.mjs";
import { parseAvatar } from "../../orb.mjs";
import { bindRowGaze, type RowGazeHandle } from "../../row-gaze.mjs";
import { COLOR_BY_ID } from "../../bloub/skins";
import { BotBody } from "./BotBody";
import { useAvatarTempo } from "./avatar-tempo";

/** What a bot is doing as a list shows it (bot-marker.mjs decides the precedence: answering > waiting > unread). */
export type AvatarStatus = "idle" | "answering" | "waiting" | "unread";

/** The bot's signature colour as a CSS colour; the ink-black and cream bodies take theme colours so the ring shows on both themes. */
function signatureColour(colour: string): string {
  if (colour === "encre") return "var(--ink)";
  if (colour === "creme") return "var(--muted)";
  return COLOR_BY_ID.get(colour)?.hex ?? "var(--ink)";
}

export interface BotAvatarProps {
  avatar: string | null | undefined; look?: unknown; name: string; seed?: string; size?: number;
  running?: boolean; unread?: boolean; frozen?: boolean; className?: string;
  /** The list's status mark.  Given (even "idle"), the avatar sits in a frame 4px wider than itself so the mark has room and the row never shifts. */
  status?: AvatarStatus;
  /** A sidebar row's avatar: while the pointer is over the row (`[data-bot-row]`) the eyes follow it. The listeners exist only during the
   * hover and are removed on leave / unmount; touch and reduced motion keep the plain idle avatar. */
  followRow?: boolean;
  rowGaze?: RowGazeHandle;
}

export function BotAvatar({ followRow = false, ...props }: BotAvatarProps) {
  return followRow ? <RowFollowing {...props} /> : <Avatar {...props} />;
}

function Avatar({ avatar, look: stored, name, seed, size = 28, running = false, unread = false, frozen = false, className = "", rowGaze, status }: BotAvatarProps) {
  const parsed = parseAvatar(avatar, name);
  const look = resolveLook(seed || name, avatar, stored, name);
  const tempo = useAvatarTempo(seed);
  const mark = parsed.kind === "text"
    ? <span data-slot="bot-avatar" className={`bot-avatar ${className}`.trim()} aria-hidden="true">{parsed.text}</span>
    : <span data-slot="bot-avatar" className={`bot-orb ${className}`.trim()} aria-hidden="true" style={{ width: size, height: size }}>
      <BotBody size={size} shape={look.shape} color={look.color} state={bloubState({ running, unread })} frozenAt={frozen ? 0 : undefined} rowGaze={rowGaze} />
    </span>;
  if (status === undefined) return mark;
  return <span data-slot="bot-status" data-status={status} className="bot-status" style={{ width: size + 4, height: size + 4, "--ring-colour": signatureColour(look.color), "--bot-tempo": tempo } as CSSProperties}>
    {status === "answering" && <span data-ring="" aria-hidden="true" className="bot-status-ring" />}
    {mark}
    {status === "waiting" && <span data-dot="" aria-hidden="true" className="bot-status-dot" />}
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
