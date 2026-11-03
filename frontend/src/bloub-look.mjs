// Bot avatar look for the bloub engine (src/bloub): which silhouette + colour a bot gets, and which engine state it shows.
// Pure functions (no engine import) so node --test can cover them.
import { DEFAULT_AVATAR, parseAvatar } from "./orb.mjs";

/** Subset of bloub's SHAPES / COLORS that read well at small sizes on both light and dark pages. */
export const BLOUB_SHAPES = ["cercle", "galet", "squircle", "hexagone", "nuage", "goutte"];
export const BLOUB_COLORS = ["encre", "brun", "rouge", "orange", "ambre", "vert", "turquoise", "bleu", "violet", "rose"];

// A face the user picked explicitly (silhouette × eye colour in the editor) maps to a fixed look.
const STYLE_SHAPE = { kline: "cercle", pure: "galet", bull: "goutte", square: "squircle" };
const MOOD_COLOR = { idle: "vert", focus: "bleu", bull: "ambre", mono: "encre" };

/** The fixed look of a silhouette × colour pick (editor swatches). */
export function faceLook(style, mood) { return { shape: STYLE_SHAPE[style], color: MOOD_COLOR[mood] }; }

/** FNV-1a, 32-bit, non-negative. */
export function hashString(value) {
  let h = 0x811c9dc5;
  for (const ch of String(value)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
  return h >>> 0;
}

/** {shape, color}: an explicit non-default `bot:<style>-<mood>` avatar wins; otherwise a stable hash of the bot id. */
export function bloubLook(id, avatar) {
  const value = String(avatar ?? "").trim();
  const parsed = parseAvatar(value);
  if (parsed.kind === "bot" && /^bot:/.test(value) && value !== DEFAULT_AVATAR) return faceLook(parsed.style, parsed.mood);
  const h = hashString(id || "finbot");
  return { shape: BLOUB_SHAPES[h % BLOUB_SHAPES.length], color: BLOUB_COLORS[Math.floor(h / BLOUB_SHAPES.length) % BLOUB_COLORS.length] };
}

/** Engine state: orbit while a turn is running, notify when there is something unread, otherwise idle. */
export function bloubState({ running = false, unread = false } = {}) {
  return running ? "orbit" : unread ? "notify" : "idle";
}
