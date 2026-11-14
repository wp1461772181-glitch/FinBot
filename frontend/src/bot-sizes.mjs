// Single source of truth for bot avatar pixel sizes (layout only) and the four size tiers of design 6.2. Narrow screens never go
// below mobileFloor: text gives way (truncate / hide the subtitle) before the avatar shrinks.
// How much animation an avatar gets depends on its tier, not on the bot:
//   XS  <= 24px      message heads, mentions      a still frame, no face change
//   S   28-40px      sidebar, lists, cards        a still frame + CSS breath at rest; frames only while hovered / working
//   M   48-64px      the chat header's live bot   the full body, per-frame, without React
//   L   96-160px     empty state, settings, login the full body, per-frame, without React
export const BOT_AVATAR_SIZE = { message: 24, sidebar: 32, title: 48, emoji: 40, mobileFloor: 44, hero: 104, createHero: 112, login: 128 };

/** The tier ranges as designed (the gaps between them are never used by a real avatar). */
export const BOT_TIERS = { XS: { min: 1, max: 24 }, S: { min: 28, max: 40 }, M: { min: 48, max: 64 }, L: { min: 96, max: 160 } };

/** The tier a pixel size belongs to; sizes in the gaps round to the nearer tier (<= 26 XS, <= 44 S, <= 80 M, above L). */
export function tierOf(size) {
  const px = Number.isFinite(size) ? size : 0;
  return px <= 26 ? "XS" : px <= 44 ? "S" : px <= 80 ? "M" : "L";
}

/** Tiers that run a frame loop for themselves (and so count against the one-per-screen rule). */
export const FULL_TIERS = ["M", "L"];
