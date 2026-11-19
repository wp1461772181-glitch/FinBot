// The memory page's small rules (P8.1), apart so a node test holds them.  The profile and recall logic proper is src/memory-items.mjs (unchanged).

/** The two tabs live in the address: ?tab=recall is 往事, anything else (or nothing) is 画像. */
export const memoryTab = (value) => (value === "recall" ? "recall" : "profile");
export const KIND_LABELS = { preference: "偏好", about_me: "关于我", instruction: "长期指令" };
export const KINDS = ["preference", "about_me", "instruction"];
export const MAX_TEXT = 200;
/** Only what the model inferred has 确认 (what the owner said or typed is already theirs). */
export const isInferred = (item) => item.origin === "inferred";
/** The scope menu of one item: 全局, each bot, and 已删除的 bot when the item's bot is not in the list any more. */
export function scopeChoices(item, bots) {
  const known = bots.some((bot) => bot.id === item.bot_id);
  return { bots, gone: Boolean(item.bot_id) && !known };
}
/** An edit that can be saved: the text is not blank. */
export const canSaveEdit = (text) => Boolean(String(text).trim());
