// Single source of truth for bot avatar pixel sizes (layout only). Narrow screens never go below mobileFloor:
// text gives way (truncate / hide the subtitle) before the avatar shrinks.
export const BOT_AVATAR_SIZE = { rail: 48, title: 48, hero: 104, createHero: 112, emoji: 40, mobileFloor: 44, sidebar: 32, login: 128 };
