import test from "node:test";
import assert from "node:assert/strict";
import { derivedDetail, excerptSource, formatStamp, isDerived, originalHref, sourceDates, sourceTypeLabel } from "../src/source-view.mjs";

test("every type the old drawer named has a phrase; an unknown type is shown as written", () => {
  assert.equal(sourceTypeLabel("saved_filing"), "已保存申报");
  assert.equal(sourceTypeLabel("reported_figure"), "SEC XBRL 披露值");
  assert.equal(sourceTypeLabel("something_new"), "something_new");
  assert.equal(sourceTypeLabel(undefined), "");
});

test("a saved AI analysis, or anything marked derived, is derived", () => {
  assert.equal(isDerived({ source_type: "saved_ai_analysis" }), true);
  assert.equal(isDerived({ source_type: "ai_analysis" }), true);
  assert.equal(isDerived({ source_type: "saved_filing", derived: true }), true);
  assert.equal(isDerived({ source_type: "saved_filing" }, { derived: true }), true);
  assert.equal(isDerived({ source_type: "saved_filing" }), false);
});

test("the derived line is version, analysis version and model, with 「v?」 when the version is unknown", () => {
  assert.equal(derivedDetail({ derived: true, version_no: 3, analysis_version: "a2", model: "m1" }), "v3 · a2 · m1");
  assert.equal(derivedDetail({ derived: true, analysis_version: "a2" }), "v? · a2");
  assert.equal(derivedDetail({ derived: false, version_no: 3 }), "");
  assert.equal(derivedDetail(null), "");
});

test("stamps: a date stays a date, an ISO time becomes local minutes, junk stays as written", () => {
  assert.equal(formatStamp("2026-11-10", "UTC"), "2026-11-10");
  assert.equal(formatStamp("2026-11-10T08:05:59Z", "UTC"), "2026-11-10 08:05");
  assert.equal(formatStamp("2026-11-10T08:05:59Z", "Asia/Shanghai"), "2026-11-10 16:05");
  assert.equal(formatStamp("last week", "UTC"), "last week");
  assert.equal(formatStamp(null, "UTC"), "");
});

test("a web page has published and fetched dates, with the old 'unknown' cases; another source its observed time", () => {
  const web = sourceDates({ source_type: "web", published_at: null, observed_at: null }, "UTC");
  assert.deepEqual([web.web, web.publishedUnknown, web.observedUnknown], [true, true, true]);
  const full = sourceDates({ source_type: "web_news", published_at: "2026-11-01", observed_at: "2026-11-02T00:00:00Z" }, "UTC");
  assert.deepEqual([full.published, full.observed, full.publishedUnknown], ["2026-11-01", "2026-11-02 00:00", false]);
  const filing = sourceDates({ source_type: "saved_filing", observed_at: "2026-11-02T00:00:00Z" }, "UTC");
  assert.deepEqual([filing.web, filing.published, filing.observedUnknown, filing.publishedUnknown], [false, null, false, false]);
  assert.equal(sourceDates({ source_type: "saved_filing" }, "UTC").observedUnknown, true);
});

test("the original is linked only when it is an http(s) page; the fetched detail wins", () => {
  assert.equal(originalHref({ source_url: "https://a.test/x" }), "https://a.test/x");
  assert.equal(originalHref({ source_url: "https://a.test/x" }, { source_url: "https://b.test/y" }), "https://b.test/y");
  assert.equal(originalHref({ source_url: "javascript:alert(1)" }), null);
  assert.equal(originalHref({ source_url: "//a.test" }), null);
  assert.equal(originalHref({}), null);
});

test("the excerpt comes from the chunk when there is one, else the citation's own quote", () => {
  assert.equal(excerptSource({ chunk_id: "c1", source_type: "saved_filing" }), "chunk");
  assert.equal(excerptSource({ chunk_id: "c1", source_type: "unavailable" }), "unavailable");
  assert.equal(excerptSource({ quote: "q" }), "quote");
  assert.equal(excerptSource({}), "none");
});
