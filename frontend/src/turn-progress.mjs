// What a kernel turn shows while it works and after (design 4.5): its sentences stacked, a checklist, a folded one-line summary.
// Only messages that carry `narration`, `checklist` or a `tier` above low get a model; every other message gets null and renders as it always did.

/** The kernel's own tools.  Their tool_start / tool_result events arrive like any tool's, but they are not lookups. */
export const KERNEL_TOOLS = ["escalate", "plan"];

const STATUSES = ["pending", "doing", "done", "failed"];
const TIER_LABELS = { mid: "中档", high: "高档" };

const list = (value) => (Array.isArray(value) ? value : []);

/** The tool-trace entries that are real lookups. */
export function lookups(toolTrace) {
  return list(toolTrace).filter((entry) => entry && typeof entry.name === "string" && entry.name !== "" && !KERNEL_TOOLS.includes(entry.name));
}

/**
 * The model of a kernel turn's progress, or null when the message is not one (or the kernel answered directly: nothing said, no list, tier low).
 * While `running` the newest sentence is `current` (it sits beside the bot's animation) and `sentences` are the ones before it.
 */
export function progressModel({ narration, checklist, tier, toolTrace, running } = {}) {
  const said = list(narration).filter((text) => typeof text === "string" && text.trim() !== "");
  const items = list(checklist).filter((item) => item && typeof item.text === "string" && item.text !== "")
    .map((item) => ({ text: item.text, status: STATUSES.includes(item.status) ? item.status : "pending" }));
  const tierLabel = typeof tier === "string" && Object.hasOwn(TIER_LABELS, tier) ? TIER_LABELS[tier] : "";
  if (said.length === 0 && items.length === 0 && !tierLabel) return null;
  const live = Boolean(running) && said.length > 0;
  return {
    sentences: live ? said.slice(0, -1) : said, current: live ? said[said.length - 1] : null,
    items, doneCount: items.filter((item) => item.status === "done").length, lookupCount: lookups(toolTrace).length, tierLabel,
  };
}

/**
 * The pieces of the one-line summary, in order, only the non-empty ones (no `seconds`: no time piece, a time nobody measured is not said).  `t` translates each template (they carry {n}, {done}, {total}
 * placeholders, filled after translating); by default the source phrases stand.
 */
export function foldedLine(model, seconds, t = (text) => text) {
  if (!model) return [];
  const pieces = [];
  if (seconds !== undefined && seconds !== null && seconds !== "") pieces.push(t("已思考 {n} 秒").replace("{n}", String(seconds)));
  if (model.lookupCount > 0) pieces.push(t("查了 {n} 次").replace("{n}", String(model.lookupCount)));
  if (model.items.length > 0) pieces.push(t("清单 {done}/{total} 项").replace("{done}", String(model.doneCount)).replace("{total}", String(model.items.length)));
  if (model.tierLabel) pieces.push(t(model.tierLabel));
  return pieces;
}
