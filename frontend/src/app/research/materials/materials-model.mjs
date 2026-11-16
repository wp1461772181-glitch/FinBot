// The material library's pure parts: the status words and their badge kinds, the filters and the chips that show them, the citation check wording.
// Phrases are zh-CN keys; the components translate them.

export const PAGE_SIZE = 10;

export const STATUS_PHRASE = { not_started: "待分析", queued: "排队中", running: "分析中", succeeded: "已分析", failed: "最近失败", blocked_data: "缺少正文" };
/** Badge kind per status (StatusBadge): waiting and blocked are neutral, a job under way is in progress, done is success, a failed attempt is failure. */
export const STATUS_KIND = { not_started: "neutral", queued: "progress", running: "progress", succeeded: "success", failed: "failure", blocked_data: "neutral" };
export const STATUSES = Object.keys(STATUS_PHRASE);

/** A blocked job carries its own reason: 「缺少正文」 is only true when the material has nothing to read; a config upgrade blocked it for another reason. */
export function statusPhrase(item) {
  if (item.analysis_status !== "blocked_data") return STATUS_PHRASE[item.analysis_status] ?? item.analysis_status;
  return item.latest_job?.safe_error_code === "config_version_changed" ? "分析配置已更新，请重新发起分析" : STATUS_PHRASE.blocked_data;
}
export const statusKind = (status) => STATUS_KIND[status] ?? "neutral";

export const DEFAULT_FILTERS = { scope: "current", order: "published", sourceType: "all", analysisStatus: "all" };
export const SOURCE_PHRASE = { official_filing: "SEC 官方", uploaded_media: "上传材料" };
export const ORDER_PHRASE = { published: "按发布时间", recent: "最近存入" };

/** The filters that differ from the defaults, as chips: [{ key, phrase, symbol? }] (the scope chip names the stock). */
export function activeFilters(filters) {
  const chips = [];
  if (filters.scope !== DEFAULT_FILTERS.scope) chips.push({ key: "scope", phrase: "全部股票" });
  if (filters.order !== DEFAULT_FILTERS.order) chips.push({ key: "order", phrase: ORDER_PHRASE[filters.order] });
  if (filters.sourceType !== "all") chips.push({ key: "sourceType", phrase: SOURCE_PHRASE[filters.sourceType] });
  if (filters.analysisStatus !== "all") chips.push({ key: "analysisStatus", phrase: STATUS_PHRASE[filters.analysisStatus] ?? filters.analysisStatus });
  return chips;
}
/** The filters with one chip taken off (back to its default). */
export const withoutFilter = (filters, key) => ({ ...filters, [key]: DEFAULT_FILTERS[key] });
/** A list with a narrowing filter on it (the order does not narrow). */
export const isNarrowed = (filters) => filters.scope !== "current" || filters.sourceType !== "all" || filters.analysisStatus !== "all";

/** 「1–10 / 12」 for the page at `offset`; 「0」 when there is nothing. */
export function pageRange(offset, total, limit = PAGE_SIZE) {
  return total ? `${offset + 1}–${Math.min(offset + limit, total)} / ${total}` : "0";
}

export const isActiveJobStatus = (status) => status === "queued" || status === "running";

/** What a job's error code says (a zh-CN phrase; an unknown code is shown as it is). */
export function jobErrorPhrase(code) {
  if (code === "no_content") return "没有可分析正文，请先读取 SEC 原文";
  if (code === "invalid_model_output") return "分析输出未通过原文引用或格式校验";
  if (code === "provider_error") return "分析服务暂时不可用";
  if (code === "analysis_model_unconfigured") return "所选分析模型尚未配置 API key，请先在 Agent 管理页设置默认模型";
  if (code === "credential_storage_unavailable") return "服务端凭据加密密钥未配置，暂时无法保存分析模型";
  if (code === "config_version_changed") return "分析配置已更新，请新建任务";
  return code || "请检查正文后重试";
}

/** The citation check of one quote: null when it matched word for word, else the note and, for a near match, its similarity as a whole percent. */
export function citationNote(citation) {
  const kind = citation.match_kind ?? "exact";
  if (kind === "fuzzy") return { kind, phrase: "近似引用", percent: Math.round((citation.similarity ?? 0) * 100) };
  if (kind === "normalized") return { kind, phrase: "规范化匹配", percent: null };
  if (kind === "unverified") return { kind, phrase: "引用待核对", percent: null };
  return null;
}

/** The analysis's check counts: the server's own when it sent them, else counted from the quotes. */
export function verificationOf(analysis) {
  if (analysis.citation_verification) return analysis.citation_verification;
  const counts = { total: 0, verified: 0, unverified: 0, exact: 0, normalized: 0, fuzzy: 0 };
  const payload = analysis.payload;
  for (const group of [payload.facts, payload.supporting, payload.counter, payload.uncertainties, payload.key_numbers]) {
    for (const item of group) for (const citation of item.citations) {
      const kind = citation.match_kind ?? "exact";
      counts.total += 1;
      if (kind === "unverified") counts.unverified += 1;
      else { counts.verified += 1; if (kind === "fuzzy") counts.fuzzy += 1; else if (kind === "normalized") counts.normalized += 1; else counts.exact += 1; }
    }
  }
  return { ...counts, verified_ratio: counts.total ? counts.verified / counts.total : 1 };
}

/** A job that is not on the server yet (the request is on its way): the page shows it as queued. */
export const PENDING_JOB = { job_id: "", status: "queued", analysis_id: null, cache_hit: false };
