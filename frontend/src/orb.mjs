// FinBot bot avatars.  A bot's avatar string is `bot:<style>-<mood>` (one of the 4 × 4 minimal round-face robots:
// silhouette × eye colour), an older `orb:<colour>` / ★ (mapped to the nearest face), or any emoji/text (shown as is).
// `bot:` rather than `finbot:` because the server caps avatars at 16 characters ("bot:square-focus" is exactly 16).
export const BOT_STYLES = ["kline", "pure", "bull", "square"];
export const BOT_MOODS = ["idle", "focus", "bull", "mono"];
export const DEFAULT_AVATAR = "bot:kline-idle";
// The old orb colours, by the mood whose eye colour is closest; `finbot` (the old brand orb) is the default face.
const LEGACY_MOOD = { finbot: "idle", green: "idle", teal: "idle", blue: "focus", purple: "focus", yellow: "bull", orange: "bull",
  brown: "bull", red: "bull", pink: "bull", black: "mono", gray: "mono" };

/** {kind:"bot", style, mood} | {kind:"text", text} for a bot's avatar. */
export function parseAvatar(avatar, name = "") {
  const value = String(avatar ?? "").trim();
  if (value === "★") return { kind: "bot", style: "kline", mood: "idle" };
  const face = value.match(/^bot:([a-z]+)-([a-z]+)$/);
  if (face && BOT_STYLES.includes(face[1]) && BOT_MOODS.includes(face[2])) return { kind: "bot", style: face[1], mood: face[2] };
  const orb = value.match(/^orb:([a-z]+)$/);
  if (orb && Object.hasOwn(LEGACY_MOOD, orb[1])) return { kind: "bot", style: "kline", mood: LEGACY_MOOD[orb[1]] };
  if (value) return { kind: "text", text: value };
  return { kind: "text", text: String(name).slice(0, 1) || "·" };
}

export function botAvatar(style, mood) {
  return BOT_STYLES.includes(style) && BOT_MOODS.includes(mood) ? `bot:${style}-${mood}` : DEFAULT_AVATAR;
}

/** The brand logo's next pose: any of the `count` poses except `current`, so the order never settles into a loop. */
export function nextPose(current, count, random = Math.random) {
  const step = 1 + Math.floor(random() * (count - 1));
  return (current + step) % count;
}
