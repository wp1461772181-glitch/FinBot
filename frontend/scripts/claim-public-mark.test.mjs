import { test } from "node:test";
import assert from "node:assert/strict";
import { renderPublicMark } from "../src/claim-public-mark.mjs";

const payload = {
  version: "public-gate-v1",
  id: "abc123",
  turn_id: "t1",
  sentence_idx: 3,
  marker: "neutral",
  hit_kind: "subject",
  template: "请对照来源 [1] 中关于「BlackRock」的原文",
  hover: {
    answer_sentence: "句子 3",
    evidence: { ordinal: 1, quote: "BlackRock removed 21,071,170 shares", completeness: "complete" },
    name_span: "BlackRock",
  },
};

test("renders the server template and evidence without adding wording", () => {
  const view = renderPublicMark(payload);
  assert.equal(view.label, payload.template);
  assert.equal(view.sentence, "句子 3");
  assert.equal(view.nameSpan, "BlackRock");
  assert.deepEqual(view.evidence, { ordinal: 1, quote: "BlackRock removed 21,071,170 shares", completeness: "complete" });
});

test("unknown completeness is shown as excerpt, never as complete", () => {
  const view = renderPublicMark({ ...payload, hover: { ...payload.hover, evidence: { ordinal: 1, quote: "x", completeness: "weird" } } });
  assert.equal(view.evidence.completeness, "excerpt");
});

test("malformed or non-neutral payloads return null so the sentence stays unmarked", () => {
  assert.equal(renderPublicMark(null), null);
  assert.equal(renderPublicMark("text"), null);
  assert.equal(renderPublicMark({ ...payload, marker: "red" }), null);
  assert.equal(renderPublicMark({ ...payload, template: undefined }), null);
  assert.equal(renderPublicMark({ ...payload, hover: undefined }), null);
});

test("ignores any judge free text carried in the payload", () => {
  const view = renderPublicMark({ ...payload, reason: "REASON-SECRET" });
  assert.equal(JSON.stringify(view).includes("REASON-SECRET"), false);
});
