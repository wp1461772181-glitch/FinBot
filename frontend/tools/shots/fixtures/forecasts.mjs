// Formal forecasts (V2): list, roots, versions with research briefs, evaluations, monitor, jobs, revision candidates.
import { ROOT, VERSION } from "./ids.mjs";
import { daysAgo, iso, lastClose } from "./common.mjs";
import { analysisId, materialId, evidenceVersionId } from "./materials.mjs";

const NV = { nvda1: "f1000000-0000-4000-8000-000000000021", nvda2: "f1000000-0000-4000-8000-000000000022", amd1: "f1000000-0000-4000-8000-000000000031" };
const ROOT_ALL = { ...ROOT, nvda: "f0000000-0000-4000-8000-000000000003", amd: "f0000000-0000-4000-8000-000000000004" };
const DECIDER = { provider: "openrouter", actual_model: "gpt-6.1-terra", question_version: "q3", time_mode: "observed", decision_mode: "llm", binding: { source: "role", role_model: "gpt-6.1-terra" }, calibration_status: "uncalibrated" };

// root -> { symbol, target, versions: [{id, ago(decision), p, trigger, reason}] , evaluation? }
const ROOTS = {
  [ROOT_ALL.aapl]: { symbol: "AAPL", target: "2026-12-31", anchor: 210.4, expired: false, versions: [
    { id: VERSION.aapl1, ago: 28, p: [0.24, 0.38, 0.38], trigger: "initial", reason: null },
    { id: VERSION.aapl2, ago: 13, p: [0.20, 0.41, 0.39], trigger: "manual_revision", reason: "新增 10-Q 与 8-K 财报材料" },
    { id: VERSION.aapl3, ago: 3, p: [0.18, 0.44, 0.38], trigger: "manual_revision", reason: "纳入券商研报与最近行情" } ] },
  [ROOT_ALL.tsla]: { symbol: "TSLA", target: "2026-11-20", anchor: 241.2, expired: false, versions: [{ id: VERSION.tsla1, ago: 18, p: [0.31, 0.29, 0.40], trigger: "initial", reason: null }] },
  [ROOT_ALL.nvda]: { symbol: "NVDA", target: "2026-10-23", anchor: 121.5, expired: true, label: "bullish", versions: [
    { id: NV.nvda1, ago: 49, p: [0.15, 0.30, 0.55], trigger: "initial", reason: null }, { id: NV.nvda2, ago: 40, p: [0.12, 0.28, 0.60], trigger: "manual_revision", reason: "新增财报材料" } ] },
  [ROOT_ALL.amd]: { symbol: "AMD", target: "2026-10-16", anchor: 151.9, expired: true, label: "neutral", versions: [{ id: NV.amd1, ago: 56, p: [0.28, 0.40, 0.32], trigger: "initial", reason: null }] },
};
export const ROOT_IDS = ROOT_ALL;

const probs = ([bearish, neutral, bullish]) => ({ bearish, neutral, bullish });
const brierOf = (p, label) => Math.round(["bearish", "neutral", "bullish"].reduce((sum, k, i) => sum + ((p[i]) - (k === label ? 1 : 0)) ** 2, 0) * 10000) / 10000;
const logLossOf = (p, label) => Math.round(-Math.log(p[["bearish", "neutral", "bullish"].indexOf(label)]) * 10000) / 10000;

function evaluationOf(root, version) {
  if (!root.label || version !== root.versions.at(-1)) return null; // only the latest version of a matured root is scored here
  return { id: `ev-${version.id}`, result_version: 1, status: "succeeded", actual_target_close: 126.4, actual_label: root.label, label_available_at: daysAgo(18), brier_score: brierOf(version.p, root.label),
    log_loss: logLossOf(version.p, root.label), direction_correct: root.label === "bullish", price_input_version: "px-v1", created_at: daysAgo(17) };
}

export function forecastList(query) {
  const symbols = (query.get("symbols") ?? "").split(",").filter(Boolean); const state = query.get("state");
  const rows = Object.entries(ROOTS).map(([id, root]) => { const v = root.versions.at(-1); const ev = evaluationOf(root, v);
    return { id, symbol: root.symbol, decision_at: daysAgo(root.versions[0].ago), target_end_date: root.target, model_status: "experimental_llm", latest_version_id: v.id, latest_version_no: root.versions.length,
      expired: root.expired, decider: DECIDER, probabilities: probs(v.p), evaluation: ev ? { status: ev.status, actual_label: ev.actual_label, result_version: ev.result_version } : null }; })
    .filter((row) => (!symbols.length || symbols.includes(row.symbol)) && (state === "all" || !state ? true : state === "open" ? !row.expired : row.expired));
  return { forecasts: rows, limit: Number(query.get("limit") ?? 200), pending_job_count: 0, job_alerts: [] };
}

export const forecastRoots = (symbol) => ({ symbol, roots: Object.entries(ROOTS).filter(([, r]) => r.symbol === symbol).map(([id, r]) => ({ id, decision_at: daysAgo(r.versions[0].ago), target_end_date: r.target, model_status: "experimental_llm", latest_version_id: r.versions.at(-1).id, latest_version_no: r.versions.length, expired: r.expired })) });

function contract(root) { return { target_end_date: root.target, horizon_sessions: 20, threshold: 0.02, anchor_close: root.anchor, anchor_date: daysAgo(root.versions[0].ago).slice(0, 10) }; }
const rootOfVersion = (versionId) => Object.entries(ROOTS).find(([, r]) => r.versions.some((v) => v.id === versionId));

export function timeline(rootId) {
  const root = ROOTS[rootId]; if (!root) return null;
  return { root_id: rootId, symbol: root.symbol, target_contract: contract(root), versions: root.versions.map((v, i) => ({ id: v.id, parent_version_id: i ? root.versions[i - 1].id : null, version_no: i + 1, decision_at: daysAgo(v.ago), market_cutoff_at: daysAgo(v.ago + 1),
    baseline_probabilities: null, joint_probabilities: null, decision_probabilities: probs(v.p), model_status: "experimental_llm", change_reason: v.reason, trigger_type: v.trigger, created_at: daysAgo(v.ago) })) };
}

const ref = (n, title, type, sel) => ({ analysis_id: analysisId(n), evidence_version_id: evidenceVersionId(n), source_type: type, source_id: materialId(n), symbol: "AAPL", title,
  source_url: type === "official_filing" ? `https://www.sec.gov/Archives/edgar/data/0000000/${n}.htm` : null, published_at: daysAgo(n === 3 ? 8 : 14), observed_at: daysAgo(n === 3 ? 7 : 13), content_sha256: "0".repeat(64), analysis_text_sha256: "1".repeat(64),
  review_status: n === 3 ? "pending_review" : "accepted", user_rating_stars: n === 3 ? 4 : null, user_rating_label: n === 3 ? "较可信（4 星）" : null, truncated: false, coverage_incomplete: false, coverage: "complete",
  selection_reason: sel, explicitly_selected: n === 3, analysis_summary: "服务业务继续增长，硬件略有下滑。", key_numbers: [] });
const ptr = (n, section, item) => ({ analysis_id: analysisId(n), section, item_id: item });

function brief(root, v, index) {
  const refs = index === 0 ? [ref(1, "10-Q 0000000000-26-000101", "official_filing", "new_in_window")] : index === 1 ? [ref(1, "10-Q 0000000000-26-000101", "official_filing", "new_in_window"), ref(2, "8-K 0000000000-26-000102", "official_filing", "new_in_window")]
    : [ref(1, "10-Q 0000000000-26-000101", "official_filing", "background"), ref(2, "8-K 0000000000-26-000102", "official_filing", "background"), ref(3, "券商研报：服务业务利润率复盘", "uploaded_media", "explicit")];
  return { schema_version: "research-brief-v1", symbol: root.symbol, decision_at: daysAgo(v.ago), time_mode: "observed", target_contract: contract(root),
    market_summary: { latest_close: lastClose(root.symbol), as_of: daysAgo(v.ago + 1), return_5_sessions: 0.0123, return_20_sessions: 0.0468, volatility_20_sessions: 0.0182, remaining_sessions: 33 - index * 5 },
    material_refs: refs,
    new_facts: [{ statement: "服务业务净销售额同比增长 14%，毛利率 75.0%。", citations: [ptr(1, "facts", "f1"), ptr(1, "facts", "f2")] }, ...(index > 0 ? [{ statement: "本季回购 240 亿美元。", citations: [ptr(2, "facts", "f1")] }] : [])],
    supporting: [{ statement: "服务收入增速高于整体，收入结构改善。", citations: [ptr(1, "supporting", "s1")] }],
    counter: [{ statement: "iPhone 收入同比下降 1%，硬件需求偏弱。", citations: [ptr(1, "counter", "c1")] }, { statement: "汇率预计带来小幅拖累。", citations: [ptr(1, "counter", "c2")] }],
    background: index > 1 ? [{ statement: "服务业务利润率长期稳定在 74% 至 75%。", continuing_reason: "多期财报一致", citations: [ptr(3, "facts", "f1")] }] : [],
    conflicts: [], unknowns: [{ question: "汇率拖累的幅度是多少？", reason: "原文没有量化", citations: [ptr(1, "uncertainties", "u1")] }],
    changes: index > 0 ? [{ change_type: "added", description: index === 1 ? "新增 10-Q 与 8-K 两份材料" : "新增 1 份用户上传的券商研报", citations: [] }] : [],
    omitted: index > 0 ? [{ source_type: "official_filing", source_id: materialId(4), analysis_id: null, reason: "analysis_unavailable" }] : [],
    input_quality: { status: "ready", reasons: [] } };
}

export function versionDetail(versionId) {
  const found = rootOfVersion(versionId); if (!found) return null;
  const [rootId, root] = found; const index = root.versions.findIndex((v) => v.id === versionId); const v = root.versions[index];
  const sources = [
    { source_type: "official_filing", source_id: materialId(1), event_key: "sec:AAPL:0000000000-26-000101", source_url: "https://www.sec.gov/Archives/edgar/data/0000000/1.htm", published_at: daysAgo(14), observed_at: daysAgo(13), event_version_id: evidenceVersionId(1), is_new: false },
    ...(index > 0 ? [{ source_type: "official_filing", source_id: materialId(2), event_key: "sec:AAPL:0000000000-26-000102", source_url: "https://www.sec.gov/Archives/edgar/data/0000000/2.htm", published_at: daysAgo(14), observed_at: daysAgo(13), event_version_id: evidenceVersionId(2), is_new: true }] : []),
    ...(index > 1 ? [{ source_type: "uploaded_media", source_id: materialId(3), source_url: null, published_at: daysAgo(8), observed_at: daysAgo(7), event_version_id: evidenceVersionId(3), is_new: true }] : []),
    ...(index > 0 ? [{ source_type: "official_filing", source_id: materialId(4), event_key: "sec:AAPL:0000000000-26-000103", source_url: "https://www.sec.gov/Archives/edgar/data/0000000/4.htm", published_at: daysAgo(21), observed_at: daysAgo(20), event_version_id: evidenceVersionId(4), is_new: false }] : []),
  ];
  return { id: v.id, root_id: rootId, parent_version_id: index ? root.versions[index - 1].id : null, job_id: `j1000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`, version_no: index + 1, symbol: root.symbol,
    target_contract: contract(root), decision_at: daysAgo(v.ago), market_cutoff_at: daysAgo(v.ago + 1), baseline_probabilities: null, joint_probabilities: null, model_status: "experimental_llm",
    decision_probabilities: probs(v.p), research_brief: root.symbol === "AAPL" ? brief(root, v, index) : null,
    model_manifest: { time_mode: "observed", decision_provider: { provider: "openrouter", requested_model: "openai/gpt-6.1-terra", actual_model: "gpt-6.1-terra", question_version: "q3", confidence: 0.62, request_id: "req-fixture-0001", input_sha256: "2".repeat(64) } },
    research_report: { status: "ready", research_conclusions_status: "ready", time_mode: "observed", automatic_selection: { explicit_source_refs: index > 1 ? [{ source_type: "uploaded_media", source_id: materialId(3) }] : [] } },
    change_reason: v.reason, trigger_type: v.trigger, created_at: daysAgo(v.ago),
    price_input_manifest: { price_input_sha256: `px${index}`.padEnd(64, "0"), market_cutoff_at: daysAgo(v.ago + 1), latest_completed_session: daysAgo(v.ago + 1).slice(0, 10), candle_count: 252 },
    evidence_version_manifest: root.symbol === "AAPL" ? sources : [], feature_snapshot: { research_brief_input_quality: "ready" } };
}

export function evaluations(symbol) {
  const rows = Object.entries(ROOTS).filter(([, r]) => r.label && (!symbol || r.symbol === symbol));
  const evRoot = ([rootId, r]) => ({ root_id: rootId, target_contract_hash: `h-${r.symbol}`, target_end_date: r.target, versions: r.versions.map((v, i) => { const e = evaluationOf(r, v);
    return { id: v.id, version_no: i + 1, decision_at: daysAgo(v.ago), trigger_type: v.trigger, model_status: "experimental_llm", time_mode: "observed", latest_evaluation: e, evaluation_history: e ? [e] : [], provider: "openrouter", actual_model: "gpt-6.1-terra", question_version: "q3",
      naive_baseline: e ? { version: "naive-vol-v1", probabilities: { bearish: 0.3, neutral: 0.4, bullish: 0.3 }, brier_score: 0.5, log_loss: 1.0 } : null }; }) });
  const roots = rows.map(evRoot);
  const empty = { status: "pending", sample: { root_denominator: 0, labelled_root_count: 0, scored_root_count: 0, unscored_root_count: 0, version_count: 0, labelled_version_count: 0, scored_version_count: 0 }, roots: [] };
  // Across every symbol the model cohort has reached the floor (30 scored roots); one symbol alone has only its own few.
  const scored = symbol ? roots.length : 31; const total = symbol ? Object.keys(ROOTS).length : 34; const labelled = symbol ? roots.length : 32;
  const state = scored >= 30 ? "available" : "insufficient_samples";
  const sample = { root_denominator: total, labelled_root_count: labelled, scored_root_count: scored, unscored_root_count: total - scored };
  return { symbol: symbol ?? null, status: state, minimum_scored_roots: 30,
    cohorts: { prospective: { time_mode: "observed", status: state, sample: { ...sample, version_count: 7, labelled_version_count: 3, scored_version_count: 3 }, roots },
      historical_research: { ...empty, time_mode: "historical_research" }, unknown: { ...empty, time_mode: "unknown" } },
    model_cohorts: [{ time_mode: "observed", model_status: "experimental_llm", provider: "openrouter", actual_model: "gpt-6.1-terra", question_version: "q3", log_loss_zero_probability_floor: 0.0001, status: state, sample,
      naive_baseline_summary: { version: "naive-vol-v1", paired_root_count: scored, baseline_unavailable_root_count: 0, model_mean_brier: 0.571, baseline_mean_brier: 0.604, model_mean_log_loss: 0.962, baseline_mean_log_loss: 1.011 },
      review_rule: { threshold: 30, paired_root_count: scored, state: state === "available" ? "passed" : "collecting" }, roots }],
    model_cohort_selection_rule: "按服务方、实际模型与问题版本分组。" };
}

export const MONITOR = { health: "healthy", schedule_interval_seconds: 3600, stale_after_seconds: 7200,
  last_run: { id: "mr000000-0000-4000-8000-000000000001", status: "succeeded", started_at: daysAgo(0, 1), completed_at: daysAgo(0, 1), next_due_at: iso(new Date(Date.parse("2026-11-13T03:00:00Z"))),
    per_symbol_results: Object.fromEntries(["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "GOOGL", "AMZN"].map((s, i) => [s, { symbol: s, status: "succeeded", discovered_count: 2 + (i % 3), created_count: i % 2, queued_count: i === 0 ? 1 : 0, skipped_count: 1, complete: true, error: null }])),
    error_summary: null, retry_reason: null },
  last_success: { id: "mr000000-0000-4000-8000-000000000001", completed_at: daysAgo(0, 1), last_success_watermark: { AAPL: daysAgo(1) } } };

export const workspace = (symbol) => { const found = Object.entries(ROOTS).find(([, r]) => r.symbol === symbol && !r.expired); if (!found) return { symbol, status: "empty", current_root: null, current_version: null, pending_job_count: 0, joint_model_status: "experimental_llm", monitor_status: "not_recorded" };
  const [rootId, root] = found; const v = root.versions.at(-1); return { symbol, status: "available", current_root: { id: rootId, target_contract: contract(root) }, current_version: { id: v.id, version_no: root.versions.length, decision_at: daysAgo(v.ago), market_cutoff_at: daysAgo(v.ago + 1), model_status: "experimental_llm", baseline_probabilities: null, joint_probabilities: null, decision_probabilities: probs(v.p), research_brief: null }, pending_job_count: 0, joint_model_status: "experimental_llm", monitor_status: "not_recorded" }; };

export const job = (id) => ({ id, symbol: "AAPL", kind: "manual_revision", root_version_id: VERSION.aapl1, parent_version_id: VERSION.aapl2, source_refs: [], time_mode: "observed", requested_decision_at: null, status: "succeeded", current_stage: "completed", attempts: 1, error: null, result_version_id: VERSION.aapl3, created_at: daysAgo(3), started_at: daysAgo(3), completed_at: daysAgo(3) });

export function revisionCandidates(versionId) { const found = rootOfVersion(versionId); const root = found?.[1]; const v = root?.versions.find((x) => x.id === versionId);
  return { version_id: versionId, version_no: root ? root.versions.indexOf(v) + 1 : 1, symbol: root?.symbol ?? "AAPL", decision_at: daysAgo(v?.ago ?? 3), window_start: daysAgo(40), window_end: daysAgo(0), target_end_date: root?.target ?? null, expired: root?.expired ?? false,
    candidates: root?.symbol === "AAPL" ? [{ source_type: "official_filing", source_id: materialId(4), title: "8-K 0000000000-26-000103", kind: "8-K", published_at: daysAgo(21), observed_at: daysAgo(20), category: "backfilled", badge: null }, { source_type: "uploaded_media", source_id: materialId(6), title: "新闻稿：欧盟 App Store 政策调整", kind: "新闻稿", published_at: daysAgo(2), observed_at: daysAgo(1), category: "new", badge: "新" }] : [], excluded: [] }; }

// --- earnings judgments ---------------------------------------------------------------------------------
const J = (id, symbol, fields) => ({ id, symbol, accession: `0000000000-26-${id.slice(-3)}`, source_url: `https://www.sec.gov/Archives/edgar/data/0000000/j-${symbol}.htm`, accepted_at: daysAgo(14), held: false, followup_status: "done", delivered: true,
  direction: "up", confidence: "medium", after_hours: 0.034, reasons: [], counter_argument: null, validated: true, model: "muse-ember", model_source: "followup", reader_version: "r2", outcome: { status: "pending", reaction: null, sigma: null }, filing_source_id: materialId(1), promotion: { available: true, reason: null }, ...fields });
export const JUDGMENTS = [
  J("e0000000-0000-4000-8000-000000000001", "AAPL", { held: true, direction: "up", confidence: "high", after_hours: 0.034, model: "muse-ember", outcome: { status: "matched", reaction: 0.028, sigma: 1.6 },
    reasons: [{ text: "服务收入增速高于预期，毛利率稳定在 75%。", quote: "Services net sales were $28.8 billion, an increase of 14% compared with the same quarter of the prior year." }, { text: "大额回购继续支撑每股收益。", quote: "During the quarter the Company repurchased $24.0 billion of its common stock." }],
    counter_argument: "iPhone 收入同比下降 1%，且管理层提示汇率将在下一季度带来小幅拖累。" }),
  J("e0000000-0000-4000-8000-000000000002", "NVDA", { accepted_at: daysAgo(11), direction: "up", confidence: "medium", after_hours: 0.052, outcome: { status: "pending", reaction: null, sigma: null }, filing_source_id: materialId(31),
    reasons: [{ text: "数据中心收入同比大幅增长，云厂商资本开支指引上调。", quote: "Data Center revenue was a record, up sharply from a year ago." }], counter_argument: "毛利率环比略降，且供给仍有限制。" }),
  J("e0000000-0000-4000-8000-000000000003", "TSLA", { accepted_at: daysAgo(20), delivered: false, direction: null, confidence: null, after_hours: null, outcome: { status: "not_applicable", reaction: null, sigma: null }, filing_source_id: materialId(21), followup_status: "skipped" }),
];
