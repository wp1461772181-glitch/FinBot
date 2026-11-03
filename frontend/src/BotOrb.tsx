// FinBot bot avatars.  A bot is drawn by the bloub engine (BloubAvatar.tsx): its silhouette and colour come from the
// avatar the user picked, or — for the default / older avatars — a stable hash of the bot id, so bots look different.
// BrandLogo is the sidebar mark: the three newspaper-reading poses (public/logo*.svg) crossfading in a random order.
// Emoji or text avatars are shown as they were.
import { useEffect, useState } from "react";
import { BloubAvatar } from "./BloubAvatar";
import { bloubState, resolveLook } from "./bloub-look.mjs";
import { nextPose, parseAvatar } from "./orb.mjs";

const BRAND_POSES = ["logo.svg", "logo-peek.svg", "logo-3d.svg"];

/** The brand mark: tilt / peek / 3-quarter poses, each held 4–8 s, the next picked at random, 600 ms crossfade.
 * Reduced motion: the tilt pose stays. */
export function BrandLogo() {
  const [pose, setPose] = useState(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let timer = 0;
    const tick = () => { timer = window.setTimeout(() => { if (document.visibilityState !== "hidden") setPose(p => nextPose(p, BRAND_POSES.length)); tick(); }, 4000 + Math.random() * 4000); };
    tick();
    return () => window.clearTimeout(timer);
  }, []);
  return <span className="brand-logo" aria-hidden="true">
    {BRAND_POSES.map((src, i) => <img key={src} src={`${import.meta.env.BASE_URL}${src}`} alt="" className={i === pose ? "is-on" : undefined} />)}
  </span>;
}

/** A bot's avatar.  `seed` (the bot id; falls back to the name) picks the hashed look; `running` / `unread` pick the state. */
export function BotOrb({ avatar, look: stored, name, seed, size = 28, running = false, unread = false, frozen = false, className = "" }: {
  avatar: string | null | undefined; look?: unknown; name: string; seed?: string; size?: number; running?: boolean; unread?: boolean; frozen?: boolean; className?: string;
}) {
  const parsed = parseAvatar(avatar, name);
  if (parsed.kind === "text") return <span className={`bot-avatar ${className}`.trim()} aria-hidden="true">{parsed.text}</span>;
  const look = resolveLook(seed || name, avatar, stored);
  return <span className={`bot-orb ${className}`.trim()} aria-hidden="true" style={{ width: size, height: size }}>
    <BloubAvatar size={size} shape={look.shape} color={look.color} expression={look.expression} state={bloubState({ running, unread })} frozenAt={frozen ? 0 : undefined} />
  </span>;
}
