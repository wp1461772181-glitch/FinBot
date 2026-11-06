// Public neutral mark (U9). The server builds each mark from structured shadow fields only: a fixed code template,
// the answer sentence, the verified source quote and its completeness. This module only reshapes that payload for
// display. It never reads a judge's free text, and it adds no wording of its own.
// Not mounted in the chat panel yet: the gate has no public mark feed and no person-review surface (see the report).

/**
 * @param {unknown} mark  one element of the server's displayable marks
 * @returns {null | {id: string, label: string, sentence: string, nameSpan: string,
 *   evidence: {ordinal: number | null, quote: string, completeness: "complete" | "excerpt"}}}
 *   null when the payload does not have the expected shape; the sentence then stays as written, unmarked.
 */
export function renderPublicMark(mark) {
  if (!mark || typeof mark !== "object") return null;
  if (mark.marker !== "neutral" || typeof mark.template !== "string" || !mark.hover) return null;
  const hover = mark.hover;
  const ev = hover.evidence && typeof hover.evidence === "object" ? hover.evidence : {};
  return {
    id: String(mark.id ?? ""),
    label: mark.template,
    sentence: String(hover.answer_sentence ?? ""),
    nameSpan: typeof hover.name_span === "string" ? hover.name_span : "",
    evidence: {
      ordinal: Number.isInteger(ev.ordinal) ? ev.ordinal : null,
      quote: String(ev.quote ?? ""),
      completeness: ev.completeness === "complete" ? "complete" : "excerpt",
    },
  };
}
