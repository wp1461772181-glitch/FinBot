// The numbers of the context card, as the server reports them (see agent_context.usage_report).
// "Remaining" is the room left in this product's history budget; it is not a model window.
export const PART_KEYS = ["system", "tools", "summary", "compressed", "recent", "free"];

function count(value) {
  const number = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return number > 0 ? Math.round(number) : 0;
}

export function normalizeContextUsage(value) {
  if (!value || typeof value !== "object") return null;
  const found = new Map();
  for (const part of Array.isArray(value.parts) ? value.parts : []) {
    if (!part || typeof part !== "object" || !PART_KEYS.includes(part.key) || found.has(part.key)) continue;
    found.set(part.key, {
      key: part.key, bytes: count(part.bytes), tokens: count(part.tokens),
      ...(typeof part.segments === "number" ? { segments: count(part.segments) } : {}),
      ...(typeof part.turns === "number" ? { turns: count(part.turns) } : {}),
    });
  }
  const capacityBytes = count(value.capacity_bytes);
  if (!capacityBytes || !found.size) return null;
  const percent = typeof value.remaining_percent === "number" && Number.isFinite(value.remaining_percent)
    ? Math.min(100, Math.max(0, Math.round(value.remaining_percent))) : 0;
  const hasHistory = typeof value.history_used_percent === "number" && Number.isFinite(value.history_used_percent);
  // Share of the history budget in use.  An older server only knows what is left of the whole capacity.
  const usedPercent = hasHistory ? Math.min(100, Math.max(0, Math.round(value.history_used_percent))) : 100 - percent;
  const compactAt = typeof value.compact_at_percent === "number" && value.compact_at_percent > 0
    ? Math.min(100, Math.round(value.compact_at_percent)) : 80;
  return {
    budgetKb: count(value.budget_kb), usedPercent, hasHistory, compactAtPercent: compactAt,
    willCompact: value.will_compact === true, capacityBytes, usedBytes: Math.min(count(value.used_bytes), capacityBytes),
    remainingBytes: count(value.remaining_bytes), remainingPercent: percent,
    compressing: value.compressing === true, hiddenTurns: count(value.hidden_turns),
    parts: PART_KEYS.filter(key => found.has(key)).map(key => found.get(key)),
  };
}

export function formatKb(bytes) {
  const kb = count(bytes) / 1024;
  return kb >= 100 ? `${Math.round(kb)} KB` : `${kb.toFixed(1)} KB`;
}

export function formatTokens(tokens) {
  const n = count(tokens);
  return n < 1000 ? String(n) : `${(n / 1000).toFixed(1)}k`;
}

/** Share of the whole bar each part takes, in percent (parts with no bytes are left out). */
export function barSegments(usage) {
  if (!usage) return [];
  return usage.parts.filter(part => part.bytes > 0)
    .map(part => ({ key: part.key, percent: Math.round((part.bytes / usage.capacityBytes) * 1000) / 10 }));
}

/** How the pill looks: plenty left, getting full, or compressing hard. */
export function meterTone(usage) {
  if (!usage) return "ok";
  if (usage.hasHistory) {            // compression starts by itself at the line, so "warn" means it is about to
    if (usage.usedPercent >= 95) return "full";
    return usage.usedPercent >= usage.compactAtPercent ? "warn" : "ok";
  }
  if (usage.remainingPercent <= 10) return "full";
  if (usage.remainingPercent <= 30) return "warn";
  return "ok";
}

const COMMAND = /^\s*\/(?:压缩|compact)(?:\s+([\s\S]*?))?\s*$/i;

/** 「/压缩」 or 「/压缩 重点保留 Intel 的分析」: the whole message is the command; the rest is the focus
 *  (the server cuts it at the same 200 characters, see agent_context_summary.parse_compact_command). */
export function parseCompactCommand(text) {
  const match = typeof text === "string" ? COMMAND.exec(text) : null;
  if (!match) return { compact: false, focus: "" };
  return { compact: true, focus: (match[1] ?? "").split(/\s+/).filter(Boolean).join(" ").slice(0, 200) };
}

export function compactLabel(turns) {
  return `已压缩 ${count(turns)} 轮`;
}

/** The server's compaction notices, usable ones only, oldest first, one per id. */
export function normalizeCompactions(list) {
  const seen = new Set();
  const notices = [];
  for (const item of Array.isArray(list) ? list : []) {
    if (!item || typeof item !== "object" || typeof item.id !== "number" || typeof item.after_turn_id !== "string" || !item.after_turn_id || seen.has(item.id)) continue;
    seen.add(item.id);
    notices.push({
      id: item.id, afterTurnId: item.after_turn_id, turns: count(item.turns), label: compactLabel(item.turns),
      summary: typeof item.summary === "string" ? item.summary : "", focus: typeof item.focus === "string" ? item.focus : "",
      createdAt: typeof item.created_at === "string" ? item.created_at : "",
    });
  }
  return notices.sort((a, b) => a.id - b.id);
}

export function noticesAfter(notices, turnId) {
  return typeof turnId === "string" && turnId ? notices.filter(notice => notice.afterTurnId === turnId) : [];
}
