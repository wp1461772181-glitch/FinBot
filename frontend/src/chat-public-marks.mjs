// Public display went live 2026-11-07 (Alan's ruling: qualifying marks display directly, no pre-review hold).
// Places the public contradiction marks (U9) on the sentences of an answer. The server sends only the gate's public
// fields (see claim-public-mark.mjs for the shape); this module finds each mark's sentence in the rendered text and
// appends one small neutral marker to that line. The sentence itself is never changed, and no wording is added here
// beyond the server's template and the verbatim source quote.

import { renderPublicMark } from "./claim-public-mark.mjs";
import { lineKey } from "./chat-unverified.mjs";

/** The visible glyph of the marker. Neutral on purpose: it says nothing about the sentence's truth. */
export const PUBLIC_MARK_GLYPH = "◦";
/** Shorter sentence keys match too many lines; a mark with a shorter key is not placed. */
const MIN_KEY = 6;

/** Keep only well-formed marks, in server order. The index of a view is its link target (`#public-mark-<index>`). */
export function normalizePublicMarks(items) {
  if (!Array.isArray(items)) return [];
  return items.map((item) => renderPublicMark(item)).filter((view) => view !== null);
}

/**
 * Append one marker link to the line that holds each mark's sentence. Returns the text unchanged when no mark
 * can be placed. A mark whose sentence is not found in the text is not shown anywhere: it is not moved to a
 * different sentence.
 */
export function attachPublicMarks(content, items) {
  const text = String(content ?? "");
  const views = normalizePublicMarks(items);
  if (!views.length) return text;
  const lines = text.split("\n");
  const keys = lines.map((line) => lineKey(line));
  const flags = new Map();
  views.forEach((view, index) => {
    const key = lineKey(view.sentence);
    if (key.length < MIN_KEY) return;
    const row = keys.findIndex((line) => line.includes(key));
    if (row < 0) return;
    flags.set(row, [...(flags.get(row) ?? []), index]);
  });
  if (!flags.size) return text;
  return lines.map((raw, row) => {
    const marks = flags.get(row);
    if (!marks) return raw;
    const suffix = marks.map((index) => ` [${PUBLIC_MARK_GLYPH}](#public-mark-${index})`).join("");
    // A table row keeps its closing bar so the marker stays inside the last cell.
    return /^\s*\|.*\|\s*$/.test(raw) ? raw.replace(/\s*\|\s*$/, `${suffix} |`) : raw + suffix;
  }).join("\n");
}

/** The index of the mark a marker link points to, or null for any other link. */
export function parsePublicMarkHref(href) {
  const match = /^#public-mark-(\d+)$/.exec(String(href ?? ""));
  return match ? Number(match[1]) : null;
}

/**
 * The source line shown under the template: the verbatim quote, with a note when the stored source is an excerpt.
 * `t` translates the fixed labels (the server's template is shown as it arrives).
 */
export const PUBLIC_MARK_LABELS = {
  quote: "来源 [{n}] 原文",
  quoteNoOrdinal: "来源原文",
  excerpt: "（节录）",
};

export function publicMarkQuoteText(view, t = (text) => text) {
  const quote = view?.evidence?.quote ?? "";
  const head = Number.isInteger(view?.evidence?.ordinal)
    ? t(PUBLIC_MARK_LABELS.quote).replace("{n}", String(view.evidence.ordinal))
    : t(PUBLIC_MARK_LABELS.quoteNoOrdinal);
  const excerpt = view?.evidence?.completeness === "complete" ? "" : t(PUBLIC_MARK_LABELS.excerpt);
  return `${head}${excerpt}：「${quote}」`;
}

/** The ordinal the reader can jump to, or null when the mark names no source. */
export function publicMarkOrdinal(view) {
  return Number.isInteger(view?.evidence?.ordinal) ? view.evidence.ordinal : null;
}

export const PUBLIC_MARK_ARIA = "对照依据";
