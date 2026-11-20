// The knowledge page's small rules (P8.1), apart so a node test holds them: the sources, the time of an upload, which kind a retrieval test asks for, which text is AI-derived.

export const SOURCES = [{ value: "faq", label: "常见问题" }, { value: "upload", label: "我的上传材料" }, { value: "sec", label: "已保存 / 已获取 SEC 摘录" }, { value: "analysis", label: "已保存 AI 分析" }];
export const QUERY_MAX = 800;
export const SYMBOL_MAX = 16;
/** The start of the text of a document that is the model's analysis, not the saved original (the page marks it so). */
export const DERIVED_PREFIX = "派生 AI 分析；";
/** The credibility and impact an upload carries: fixed, not chosen on this page. */
export const FIXED_STARS = 3;
export const FIXED_IMPACT = "medium";

const pad = (value) => String(value).padStart(2, "0");
/** A local date and time as a datetime-local box holds it. */
export const localDateTimeInput = (date = new Date()) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
/** The date of a datetime-local value as the local time it names; null when it is not a real time. */
export function parseLocalDateTime(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(String(value ?? ""));
  if (!match) return null;
  const [, year, month, day, hour, minute] = match.map(Number);
  const date = new Date(year, month - 1, day, hour, minute);
  return date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day || date.getHours() !== hour || date.getMinutes() !== minute ? null : date;
}

/** The kind a retrieval test asks for, from the source chosen above it: 常见问题 → faq, AI 分析 → analysis, everything else → material. */
export const retrievalKind = (source) => (source === "faq" ? "faq" : source === "analysis" ? "analysis" : "material");
/** The arguments of testKnowledgeRetrieval: the kind, the query, and the code (none for 常见问题). */
export const retrievalArgs = (source, query, symbol) => [retrievalKind(source), query, source === "faq" ? undefined : symbol];

/** An upload can be sent when it has a file, a title, a link and a reason (the old button's rule). */
export const uploadReady = ({ file, title, url, reason }) => Boolean(file && title && url && reason);
/** The text of a document is the AI's analysis, not the original. */
export const isDerivedText = (text) => String(text ?? "").startsWith(DERIVED_PREFIX);
/** The retrieval answer as the page shows it: the two parts as JSON. */
export const retrievalText = (answer) => JSON.stringify({ result: answer.result, citations: answer.citations }, null, 2);
