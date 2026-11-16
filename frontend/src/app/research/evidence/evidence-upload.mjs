// The upload form's rules, kept exactly as the old form had them (its submit button waited for every one of these): a file of a kind we read, a title,
// an https source, a publication time, a reason for the rating.  The stars (1–5, 3 by default) and the impact (low / medium / high, medium by default)
// can not be wrong: they are picked from a fixed set.

export const TITLE_MAX = 240;
export const REASON_MAX = 1000;
export const FILE_ACCEPT = ".txt,.md,.markdown,.pdf,text/plain,text/markdown,application/pdf";
export const IMPACTS = ["low", "medium", "high"];

export function isHttpsUrl(value) {
  try { return new URL(String(value).trim()).protocol === "https:"; } catch { return false; }
}

/** A file is one we read when its name ends .txt / .md / .markdown / .pdf (any case) or its type says text, markdown or PDF. */
export function isAllowedEvidenceFile(file) {
  return /\.(txt|md|markdown|pdf)$/i.test(file.name) || ["text/plain", "text/markdown", "application/pdf"].includes(file.type);
}

/** The fields that are wrong: { file?, title?, sourceUrl?, publishedAt?, reason? } with a code each; {} when the form may be sent. */
export function validateUpload({ file, title, sourceUrl, publishedAt, reason }) {
  const errors = {};
  if (!file) errors.file = "missing";
  else if (!isAllowedEvidenceFile(file)) errors.file = "type";
  if (!String(title).trim()) errors.title = "missing";
  if (!isHttpsUrl(sourceUrl)) errors.sourceUrl = String(sourceUrl).trim() ? "not-https" : "missing";
  if (!publishedAt) errors.publishedAt = "missing";
  if (!String(reason).trim()) errors.reason = "missing";
  return errors;
}

/** The input of `uploadEvidence`: texts trimmed, the time (a local date-time the reader picked) as UTC ISO, as the old form sent it. */
export function uploadInput({ file, title, sourceUrl, publishedAt, stars, impact, reason }) {
  return { file, title: title.trim(), sourceUrl: sourceUrl.trim(), publishedAt: new Date(publishedAt).toISOString(), credibilityStars: stars, credibilityReason: reason.trim(), impactSeverity: impact };
}

/** The first field to take the focus when the form is refused, in reading order. */
export const FIELD_ORDER = ["file", "title", "sourceUrl", "publishedAt", "reason"];
export const firstInvalid = (errors) => FIELD_ORDER.find((field) => errors[field]) ?? null;
