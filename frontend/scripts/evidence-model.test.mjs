import assert from "node:assert/strict";
import test from "node:test";
import { EVENT_GROUPS, briefModel, clampStars, eventCount, eventGroups, httpsUrl, latestVersionId, sectionPhrase, sortUploaded, sourceTypeLabel } from "../src/app/research/evidence/evidence-model.mjs";

const ptr = (analysis, section, item) => ({ analysis_id: analysis, section, item_id: item });
const brief = {
  supporting: [{ statement: "利好一", citations: [ptr("a1", "supporting", "s1")] }, { statement: "别家的利好", citations: [ptr("a2", "supporting", "s1")] }],
  counter: [{ statement: "利空一", citations: [ptr("a1", "counter", "c1"), ptr("a2", "counter", "c1")] }],
  new_facts: [{ statement: "事实一", citations: [ptr("a1", "facts", "f1"), ptr("a1", "facts", "f2")] }],
  background: [{ statement: "背景", continuing_reason: "多期一致", citations: [ptr("a1", "facts", "f1")] }],
  conflicts: [], unknowns: [{ question: "幅度？", reason: "未量化", citations: [ptr("a1", "uncertainties", "u1")] }],
  changes: [{ change_type: "added", description: "新增一份", citations: [ptr("a1", "facts", "f1")] }, { change_type: "modified", description: "无引用", citations: [] }],
};
const t = (text) => text;

test("a material's events are the statements that cite its analysis, in the design's group order", () => {
  const groups = eventGroups(brief, "a1", t, "zh-CN");
  assert.deepEqual(groups.map((g) => g.key), ["supporting", "counter", "facts", "background", "unknowns", "changes"]);
  assert.equal(groups.find((g) => g.key === "supporting").rows.length, 1);
  assert.equal(groups.find((g) => g.key === "supporting").rows[0].text, "利好一");
  assert.equal(eventCount(groups), 6);
});

test("a statement keeps only the citations into this analysis; one with none left is not this material's", () => {
  const counter = eventGroups(brief, "a1", t, "zh-CN").find((g) => g.key === "counter");
  assert.deepEqual(counter.rows[0].citations.map((c) => c.analysis_id), ["a1"]);
  assert.deepEqual(eventGroups(brief, "a3", t, "zh-CN"), []);
  assert.equal(eventGroups(brief, "a2", t, "zh-CN").length, 2);
});

test("the composed lines follow the language", () => {
  const zh = eventGroups(brief, "a1", t, "zh-CN"), en = eventGroups(brief, "a1", t, "en-US");
  assert.equal(zh.find((g) => g.key === "background").rows[0].text, "背景（持续原因：多期一致）");
  assert.equal(en.find((g) => g.key === "background").rows[0].text, "背景 (Continuing reason: 多期一致)");
  assert.equal(zh.find((g) => g.key === "unknowns").rows[0].text, "幅度？：未量化");
  assert.equal(en.find((g) => g.key === "unknowns").rows[0].text, "幅度？: 未量化");
  assert.equal(zh.find((g) => g.key === "changes").rows[0].text, "新增: 新增一份");
  assert.deepEqual(EVENT_GROUPS.map((g) => g.key).slice(0, 2), ["supporting", "counter"]);
});

test("small labels", () => {
  assert.equal(sectionPhrase("facts"), "事实"); assert.equal(sectionPhrase("uncertainties"), "不确定项");
  assert.equal(sourceTypeLabel("official_filing", "zh-CN"), "SEC 官方文件"); assert.equal(sourceTypeLabel("uploaded_media", "en-US"), "Uploaded media");
  assert.equal(clampStars(0), 1); assert.equal(clampStars(7), 5); assert.equal(clampStars(3.4), 3);
  assert.deepEqual(sortUploaded([{ id: "a", published_at: "2026-01-01" }, { id: "b", published_at: "2026-02-01" }]).map((i) => i.id), ["b", "a"]);
  assert.equal(briefModel({ model_manifest: { decision_provider: { actual_model: "gpt-6.1-terra" } } }), "gpt-6.1-terra");
  assert.equal(briefModel({ model_manifest: {} }), null); assert.equal(briefModel(null), null);
  assert.equal(latestVersionId([{ latest_version_id: "v9" }, { latest_version_id: "v1" }]), "v9"); assert.equal(latestVersionId([]), null);
  assert.equal(httpsUrl("https://a.b/c"), "https://a.b/c"); assert.equal(httpsUrl("http://a.b"), null); assert.equal(httpsUrl(null), null);
});
