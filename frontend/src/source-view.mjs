// How a citation reads as a source card.  Every field of the old 引用来源 drawer is here: the ordinal, the derived mark, the
// SEC XBRL mark, title and section, the dates (web pages: published and fetched), the truncated note, the stored quote, the fetched
// excerpt with its original quotes, and the link to the original.  Words are source phrases; the caller translates them.

/** Source types whose link opens straight to the original (the old drawer opened these in a new tab on click). */
export const LINKED_TYPES = ["web", "web_news", "official_filing", "saved_filing", "saved_ai_analysis", "reported_figure"];
const WEB_TYPES = ["web", "web_news"];

const TYPE_LABELS = {
  web: "网页",
  web_news: "新闻网页",
  official_filing: "官方申报",
  saved_filing: "已保存申报",
  saved_ai_analysis: "已保存 AI 分析",
  ai_analysis: "已保存 AI 分析",
  reported_figure: "SEC XBRL 披露值",
  unavailable: "来源已撤回或不可访问",
};

/** The phrase naming a source type; a type this table does not know is shown as the server wrote it. */
export function sourceTypeLabel(type) {
  const key = typeof type === "string" ? type : "";
  return TYPE_LABELS[key] ?? key;
}

/** A saved AI analysis is derived content, not an original: its card says so (a mark of provenance, not a warning). */
export function isDerived(citation, detail) {
  return Boolean(citation?.derived) || Boolean(detail?.derived) || citation?.source_type === "ai_analysis" || citation?.source_type === "saved_ai_analysis";
}

/** The line under a derived excerpt: version, analysis version, model (the old drawer's 「v? · … · …」). */
export function derivedDetail(detail) {
  if (!detail?.derived) return "";
  return [`v${detail.version_no ?? "?"}`, detail.analysis_version, detail.model].filter(Boolean).join(" · ");
}

/** An ISO stamp as `YYYY-MM-DD HH:mm` in the reader's zone; a plain date stays a date; anything else stays as written. */
export function formatStamp(value, zone) {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(parsed);
  const get = (type) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

/**
 * The dates of a card.  A web page has a published and a fetched date (the old drawer said 「发布日期未知」 / 「抓取 时间未知」 when it
 * had none); any other source has its observed time (「观察时间未知」).  A source that is not a web page shows a published date only when
 * it has one.
 */
export function sourceDates(citation, zone) {
  const web = WEB_TYPES.includes(citation?.source_type);
  const published = formatStamp(citation?.published_at, zone);
  const observed = formatStamp(citation?.observed_at, zone);
  if (web) return { published: published || null, publishedUnknown: !published, observed: observed || null, observedUnknown: !observed, web: true };
  return { published: published || null, publishedUnknown: false, observed: observed || null, observedUnknown: !observed, web: false };
}

/** The address of the original, only when it is an http(s) page; a `javascript:` or other scheme is never made into a link. */
export function originalHref(citation, detail) {
  for (const value of [detail?.source_url, citation?.source_url]) {
    if (typeof value === "string" && /^https?:\/\//i.test(value.trim())) return value.trim();
  }
  return null;
}

/** What the card shows as the quote: a citation held in the knowledge store is read through its chunk; any other brings its own quote. */
export function excerptSource(citation) {
  if (citation?.source_type === "unavailable") return "unavailable";
  if (citation?.chunk_id) return "chunk";
  return citation?.quote ? "quote" : "none";
}
