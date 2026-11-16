import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_FILTERS, PAGE_SIZE, STATUSES, activeFilters, citationNote, isNarrowed, jobErrorPhrase, pageRange, statusKind, statusPhrase, verificationOf, withoutFilter } from "../src/app/research/materials/materials-model.mjs";

test("the six statuses keep their words and their badge kinds", () => {
  assert.deepEqual(STATUSES.map((s) => statusPhrase({ analysis_status: s, latest_job: null })), ["待分析", "排队中", "分析中", "已分析", "最近失败", "缺少正文"]);
  assert.deepEqual(STATUSES.map(statusKind), ["neutral", "progress", "progress", "success", "failure", "neutral"]);
  assert.equal(statusKind("something-new"), "neutral");
});

test("a blocked job blocked by a config upgrade says so, not 缺少正文", () => {
  assert.equal(statusPhrase({ analysis_status: "blocked_data", latest_job: { safe_error_code: "config_version_changed" } }), "分析配置已更新，请重新发起分析");
  assert.equal(statusPhrase({ analysis_status: "blocked_data", latest_job: { safe_error_code: "no_content" } }), "缺少正文");
});

test("a filter that differs from its default is a chip, and removing the chip restores the default", () => {
  assert.deepEqual(activeFilters(DEFAULT_FILTERS), []);
  const all = { scope: "all", order: "recent", sourceType: "uploaded_media", analysisStatus: "failed" };
  assert.deepEqual(activeFilters(all).map((c) => c.key), ["scope", "order", "sourceType", "analysisStatus"]);
  assert.deepEqual(activeFilters(all).map((c) => c.phrase), ["全部股票", "最近存入", "上传材料", "最近失败"]);
  assert.deepEqual(withoutFilter(all, "sourceType"), { ...all, sourceType: "all" });
  assert.deepEqual(withoutFilter(withoutFilter(withoutFilter(withoutFilter(all, "scope"), "order"), "sourceType"), "analysisStatus"), DEFAULT_FILTERS);
});

test("only filters that narrow the list make an empty list a 筛选无结果", () => {
  assert.equal(isNarrowed(DEFAULT_FILTERS), false);
  assert.equal(isNarrowed({ ...DEFAULT_FILTERS, order: "recent" }), false);
  assert.equal(isNarrowed({ ...DEFAULT_FILTERS, scope: "all" }), true);
  assert.equal(isNarrowed({ ...DEFAULT_FILTERS, analysisStatus: "failed" }), true);
});

test("the page range", () => {
  assert.equal(PAGE_SIZE, 10);
  assert.equal(pageRange(0, 12), "1–10 / 12"); assert.equal(pageRange(10, 12), "11–12 / 12"); assert.equal(pageRange(0, 0), "0");
});

test("a quote's check is a note only when it was not word for word", () => {
  assert.equal(citationNote({ quote: "q" }), null);
  assert.equal(citationNote({ quote: "q", match_kind: "exact" }), null);
  assert.deepEqual(citationNote({ quote: "q", match_kind: "fuzzy", similarity: 0.934 }), { kind: "fuzzy", phrase: "近似引用", percent: 93 });
  assert.deepEqual(citationNote({ quote: "q", match_kind: "normalized" }), { kind: "normalized", phrase: "规范化匹配", percent: null });
  assert.deepEqual(citationNote({ quote: "q", match_kind: "unverified" }), { kind: "unverified", phrase: "引用待核对", percent: null });
});

test("the check counts: the server's, or counted from the quotes", () => {
  const server = { total: 9, verified: 9, unverified: 0, exact: 9, normalized: 0, fuzzy: 0, verified_ratio: 1 };
  assert.equal(verificationOf({ citation_verification: server, payload: {} }), server);
  const c = (match_kind) => ({ quote: "q", match_kind });
  const payload = { facts: [{ citations: [c("exact"), c("unverified")] }], supporting: [{ citations: [c("fuzzy")] }], counter: [], uncertainties: [{ citations: [c("normalized")] }], key_numbers: [] };
  const v = verificationOf({ citation_verification: null, payload });
  assert.deepEqual([v.total, v.verified, v.unverified, v.exact, v.fuzzy, v.normalized], [4, 3, 1, 1, 1, 1]);
  assert.equal(verificationOf({ payload: { facts: [], supporting: [], counter: [], uncertainties: [], key_numbers: [] } }).verified_ratio, 1);
});

test("job error phrases", () => {
  assert.equal(jobErrorPhrase("no_content"), "没有可分析正文，请先读取 SEC 原文");
  assert.equal(jobErrorPhrase("provider_timeout"), "provider_timeout");
  assert.equal(jobErrorPhrase(null), "请检查正文后重试");
});
