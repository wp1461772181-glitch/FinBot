// The material library (资料库): filings and uploaded media with analyses in assorted states, plus the analyses themselves.
import { daysAgo, iso } from "./common.mjs";

const mid = (n) => `m0000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const aid = (n) => `a1000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const evid = (n) => `ee000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const materialId = mid; export const analysisId = aid; export const evidenceVersionId = evid;

// [n, symbol, type, title, published days ago, analysis status, review status, analysisNo|null, extra]
const ROWS = [
  [1, "AAPL", "official_filing", "10-Q 0000000000-26-000101", 14, "succeeded", "accepted", 1],
  [2, "AAPL", "official_filing", "8-K 0000000000-26-000102", 14, "succeeded", "accepted", 2],
  [3, "AAPL", "uploaded_media", "券商研报：服务业务利润率复盘", 8, "succeeded", "pending_review", 3],
  [4, "AAPL", "official_filing", "8-K 0000000000-26-000103", 21, "not_started", "pending_review", null],
  [5, "AAPL", "official_filing", "10-K 0000000000-26-000104", 75, "not_started", "pending_review", null],
  [6, "AAPL", "uploaded_media", "新闻稿：欧盟 App Store 政策调整", 2, "queued", "pending_review", null],
  [7, "AAPL", "official_filing", "8-K 0000000000-26-000105", 62, "failed", "pending_review", null],
  [8, "AAPL", "official_filing", "10-Q 0000000000-26-000106", 105, "succeeded", "accepted", 4],
  [9, "AAPL", "uploaded_media", "访谈纪要：供应链负责人", 26, "blocked_data", "pending_review", null],
  [10, "AAPL", "official_filing", "8-K 0000000000-26-000107", 120, "succeeded", "accepted", 5],
  [11, "AAPL", "official_filing", "8-K 0000000000-26-000108", 145, "not_started", "pending_review", null],
  [12, "AAPL", "official_filing", "10-Q 0000000000-26-000109", 195, "succeeded", "accepted", 6],
  [21, "TSLA", "official_filing", "10-Q 0000000000-26-000201", 20, "succeeded", "accepted", 7],
  [22, "TSLA", "uploaded_media", "产能爬坡跟踪笔记", 9, "not_started", "pending_review", null],
  [23, "TSLA", "official_filing", "8-K 0000000000-26-000202", 33, "not_started", "pending_review", null],
  [31, "NVDA", "official_filing", "10-Q 0000000000-26-000301", 11, "succeeded", "accepted", 8],
  [32, "NVDA", "official_filing", "8-K 0000000000-26-000302", 11, "not_started", "pending_review", null],
  [33, "AMD", "official_filing", "10-Q 0000000000-26-000401", 16, "succeeded", "accepted", 9],
];

function job(status, analysisNo, ago) {
  if (status === "not_started") return null;
  return { job_id: `j0000000-0000-4000-8000-${String(analysisNo ?? 99).padStart(12, "0")}`, status, analysis_id: analysisNo ? aid(analysisNo) : null, cache_hit: false,
    ...(status === "failed" ? { safe_error_code: "provider_timeout" } : {}), ...(status === "blocked_data" ? { safe_error_code: "no_content" } : {}),
    current_stage: status === "queued" ? "queued" : "done", attempts: 1, created_at: daysAgo(ago), completed_at: ["queued", "running"].includes(status) ? null : daysAgo(ago) };
}

export const MATERIALS = ROWS.map(([n, symbol, type, title, ago, status, review, analysisNo]) => ({
  symbol, source_type: type, source_id: mid(n), title, published_at: daysAgo(ago), observed_at: daysAgo(ago - 1),
  source_url: type === "official_filing" ? `https://www.sec.gov/Archives/edgar/data/0000000/${n}.htm` : "",
  latest_analysis_id: analysisNo ? aid(analysisNo) : null, latest_analysis_version_no: analysisNo ? 1 : null, latest_analysis_created_at: analysisNo ? daysAgo(Math.max(0, ago - 1)) : null,
  latest_analysis_evidence_version_id: analysisNo ? evid(n) : null, analysis_status: status, latest_job: job(status, analysisNo, Math.max(0, ago - 1)),
  review_status: review, coverage: status === "succeeded" ? "complete" : null, can_view_original: status !== "blocked_data", can_download_original: type === "uploaded_media" && status !== "blocked_data",
}));

export function materialList(query) {
  const symbol = query.get("symbol"); const type = query.get("source_type"); const status = query.get("analysis_status"); const review = query.get("review_status");
  const limit = Number(query.get("limit") ?? 10); const offset = Number(query.get("offset") ?? 0);
  let items = MATERIALS.filter((m) => (!symbol || m.symbol === symbol) && (!type || m.source_type === type) && (!status || m.analysis_status === status) && (!review || m.review_status === review));
  if (query.get("order") === "recent") items = [...items].sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at)));
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
}

const cite = (quote, start) => ({ quote, start_char: start, end_char: start + quote.length, match_kind: "exact", similarity: 1, original_quote: null });
const Q = {
  services: "Services net sales were $28.8 billion, an increase of 14% compared with the same quarter of the prior year.",
  margin: "Services gross margin percentage was 75.0%, compared with 74.9% in the prior year quarter.",
  fx: "The Company expects a modest foreign exchange headwind in the first quarter of fiscal 2027.",
  buyback: "During the quarter the Company repurchased $24.0 billion of its common stock.",
  iphone: "iPhone net sales were $46.2 billion, a decrease of 1% compared with the same quarter of the prior year.",
};
export const FROZEN_TEXT = `Item 2. Management's Discussion and Analysis\n\n${Q.services}\n${Q.iphone}\n${Q.margin}\n\nLiquidity and capital resources\n${Q.buyback}\n${Q.fx}\n`;

export function analysisVersion(n, { versionNo = 1, symbol = "AAPL" } = {}) {
  const id = aid(n);
  const row = MATERIALS.find((m) => m.latest_analysis_id === id);
  const at = FROZEN_TEXT;
  const find = (quote) => at.indexOf(quote);
  return {
    analysis_id: id, source_type: row?.source_type ?? "official_filing", source_id: row?.source_id ?? mid(n), evidence_version_id: row?.latest_analysis_evidence_version_id ?? evid(n),
    version_no: versionNo, previous_version_id: null, requested_model: "muse-ember", actual_model: "muse-ember", created_at: daysAgo(13),
    payload: {
      summary: `${symbol} 本季服务收入继续两位数增长、毛利率稳定，硬件收入略有下滑；管理层提示下一季度汇率会带来小幅拖累，并保持大额回购。`,
      facts: [
        { id: "f1", statement: "服务业务净销售额为 288 亿美元，同比增长 14%。", citations: [cite(Q.services, find(Q.services))] },
        { id: "f2", statement: "服务毛利率为 75.0%，上年同期为 74.9%。", citations: [cite(Q.margin, find(Q.margin))] },
        { id: "f3", statement: "本季回购普通股 240 亿美元。", citations: [cite(Q.buyback, find(Q.buyback))] },
      ],
      supporting: [
        { id: "s1", statement: "服务收入增速高于整体，利润率高，收入结构在改善。", rationale: "服务业务占比提升会抬高整体毛利率。", fact_ids: ["f1", "f2"], citations: [cite(Q.services, find(Q.services))] },
        { id: "s2", statement: "大额回购支撑每股收益。", rationale: "回购减少流通股数。", fact_ids: ["f3"], citations: [cite(Q.buyback, find(Q.buyback))] },
      ],
      counter: [
        { id: "c1", statement: "iPhone 收入同比下降 1%，硬件需求偏弱。", rationale: "硬件仍是收入的最大来源。", fact_ids: [], citations: [cite(Q.iphone, find(Q.iphone))] },
        { id: "c2", statement: "汇率预计在下一季度带来小幅拖累。", rationale: "会压低报告口径的增速。", fact_ids: [], citations: [cite(Q.fx, find(Q.fx))] },
      ],
      uncertainties: [{ id: "u1", statement: "汇率拖累的具体幅度没有量化。", reason: "原文只说 modest，没有给出区间。", citations: [cite(Q.fx, find(Q.fx))] }],
      key_numbers: [
        { name: "服务净销售额", value_text: "$28.8B（+14% 同比）", period: "2026 财年第四季度", citations: [cite(Q.services, find(Q.services))] },
        { name: "服务毛利率", value_text: "75.0%", period: "2026 财年第四季度", citations: [cite(Q.margin, find(Q.margin))] },
        { name: "iPhone 净销售额", value_text: "$46.2B（-1% 同比）", period: "2026 财年第四季度", citations: [cite(Q.iphone, find(Q.iphone))] },
      ],
    },
    source_manifest: { content_sha256: "0".repeat(64), truncated: false },
    citation_verification: { total: 9, verified: 9, unverified: 0, exact: 9, normalized: 0, fuzzy: 0, verified_ratio: 1 },
    frozen_text: FROZEN_TEXT, source_snapshot: {},
  };
}

export function materialOriginal(type, id) {
  const row = MATERIALS.find((m) => m.source_id === id) ?? MATERIALS[0];
  return { symbol: row.symbol, source_type: type, source_id: id, title: row.title, source_url: row.source_url, content_text: FROZEN_TEXT, content_status: "fetched", content_error: null,
    coverage: "complete", truncated: false, can_download: row.can_download_original, can_fetch: row.source_type === "official_filing", document_name: row.source_type === "uploaded_media" ? "report.pdf" : null };
}

export const ANALYSIS_SETTINGS = { source: "settings", provider: "openrouter", base_url: null, model: "muse/ember", has_api_key: true, api_key_last4: null };
export { iso };
