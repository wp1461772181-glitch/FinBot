// Sentences the server could not check against a source are kept in the answer and reported as
// `unverified_lines: [{ line, reason, numbers }]`. This module finds those sentences in the rendered
// text and marks them, so the answer reads as written and the doubt sits next to the sentence.

/** Phrase keys (zh-CN catalogue) for the reason codes the server reports. */
export const REASON_KEYS = {
  unsupported_numeric_claim: "数字与引用的来源对不上",
  unsupported_numeric: "数字与引用的来源对不上",
  insufficient_numeric_evidence: "来源内容不完整，这个数字无法核实",
  field_mismatch: "数字与引用的来源对不上",
  missing_citation: "这句话没有标注来源",
  invalid_citation: "引用的来源编号不存在",
  unsupported_claim: "引用的来源里找不到这个说法",
  quote_not_found: "引用的来源里找不到这个说法",
  quote_too_short: "引用的来源里找不到这个说法",
  claims_missing: "没有给出可核对的依据",
  derived_requires_calculate: "推算值没有对应的计算结果",
  source_part_not_stored: "引用的 8-K 申报仅保存了部分文件（仅附件 99.1 或仅主表），该细节无法在库内核对",
};
export const DEFAULT_REASON_KEY = "未能与来源核对";

const MARKER = /\[\d+(?:\s*[,，、;；]\s*\d+)*\]/g;
const LEAD = /^\s*(?:[-*+•]\s+|\d+[.)、]\s*|>\s*)/;
const MIN_PREFIX = 60;

/** A line with its citation markers, list bullet, table bars and spacing removed: the identity of a sentence. */
export function lineKey(line) {
  return String(line ?? "").replace(MARKER, "").replace(LEAD, "").replace(/\|/g, " ").replace(/\s+/g, "");
}

/** Keep only well-formed items; the server's list is untrusted display data. */
export function normalizeUnverified(items) {
  if (!Array.isArray(items)) return [];
  return items
    .filter((item) => item && typeof item.line === "string" && lineKey(item.line))
    .map((item) => ({
      line: item.line,
      reason: typeof item.reason === "string" ? item.reason : "",
      numbers: Array.isArray(item.numbers) ? item.numbers.filter((n) => typeof n === "string" && n.trim()).map((n) => n.trim()) : [],
    }));
}

export function reasonKey(reason) {
  return REASON_KEYS[reason] ?? DEFAULT_REASON_KEY;
}

function sameSentence(contentKey, itemKey) {
  if (!contentKey || !itemKey) return false;
  if (contentKey === itemKey) return true;
  // The server shortens long lines to 400 characters.
  return itemKey.length >= MIN_PREFIX && contentKey.startsWith(itemKey);
}

/** For each line of `content`, the index of the unverified item that names it (or -1). Each item marks one line. */
export function matchLines(content, items) {
  const list = normalizeUnverified(items);
  const used = new Set();
  return String(content ?? "").split("\n").map((raw) => {
    const key = lineKey(raw);
    if (!key) return -1;
    const index = list.findIndex((item, i) => !used.has(i) && sameSentence(key, lineKey(item.line)));
    if (index >= 0) used.add(index);
    return index;
  });
}

const escapeLabel = (text) => String(text).replace(/[[\]\\]/g, "").replace(/\s+/g, " ").trim();

/**
 * Append the flags to the matching lines. Each flag is a markdown link, `#unverified-<n>` (not enough evidence) or
 * `#unverified-num-<n>` (a number no source holds), which the renderer turns into a badge. `labels` carries the
 * already translated texts: `{ insufficient, numbers, reason(code) }`. The sentence itself is never changed.
 */
export function markUnverified(content, items, labels) {
  const text = String(content ?? "");
  const list = normalizeUnverified(items);
  if (!list.length) return text;
  const matched = matchLines(text, list);
  return text.split("\n").map((raw, row) => {
    const index = matched[row];
    if (index < 0) return raw;
    const item = list[index];
    const flags = [`[${escapeLabel(`${labels.insufficient}：${labels.reason(item.reason)}`)}](#unverified-${index})`];
    if (item.numbers.length) flags.push(`[${escapeLabel(`${labels.numbers}：${item.numbers.join("、")}`)}](#unverified-num-${index})`);
    const suffix = ` ${flags.join(" ")}`;
    // A table row keeps its closing bar so the flag stays inside the last cell.
    return /^\s*\|.*\|\s*$/.test(raw) ? raw.replace(/\s*\|\s*$/, `${suffix} |`) : raw + suffix;
  }).join("\n");
}

/** `{ kind: "insufficient" | "numbers", index }` for a flag link, otherwise null. */
export function parseFlagHref(href) {
  const match = /^#unverified-(num-)?(\d+)$/.exec(String(href ?? ""));
  return match ? { kind: match[1] ? "numbers" : "insufficient", index: Number(match[2]) } : null;
}

/** The sentence as the owner would repeat it: no markers, bullet or table bars. */
export function plainSentence(line) {
  return String(line ?? "").replace(MARKER, "").replace(LEAD, "").replace(/\|/g, " ").replace(/\s+/g, " ").replace(/\s+([。！？，、；：.!?,;:])/g, "$1").trim();
}

/** The text the 「追问依据」 button puts into the input box. */
export function followUpQuestion(line) {
  return `这句话的依据是什么：${plainSentence(line)}`;
}
