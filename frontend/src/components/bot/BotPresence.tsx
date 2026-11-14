// The bot standing in the chat (the chat header, the empty state, the login page). The live part (the director, the personality, the
// per-frame drive) is a chunk of its own: the first paint shows the same avatar as a still frame and the live one takes its place a moment
// later (and the still one stays if that chunk never arrives), so none of that code is in the first-screen download.
import { lazy } from "react";
import { LiveSlot } from "../../LiveSlot";
import { BotAvatar } from "./BotAvatar";
import type { BotPresenceProps } from "./BotPresenceLive";

const Live = lazy(() => import("./BotPresenceLive"));

export type { BotPresenceProps };

export function BotPresence(props: BotPresenceProps) {
  const { avatar, look, name, seed, size, className } = props;
  return <LiveSlot fallback={<BotAvatar avatar={avatar} look={look} name={name} seed={seed} size={size} className={`bot-orb-live ${className ?? ""}`.trim()} />}>
    <Live {...props} />
  </LiveSlot>;
}
