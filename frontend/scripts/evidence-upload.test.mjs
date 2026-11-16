// The new upload form must let through exactly what the old one did (P6.3, acceptance 3): every case recorded from the old form is replayed
// against the rules module, and what the old form sent is what `uploadInput` builds.
process.env.TZ = "Asia/Shanghai"; // the baseline was recorded in this zone: a local date-time becomes UTC through it
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { CASES, VALID } from "../tools/shots/fixtures/upload-cases.mjs";
import { FIELD_ORDER, FILE_ACCEPT, REASON_MAX, TITLE_MAX, firstInvalid, isAllowedEvidenceFile, isHttpsUrl, uploadInput, validateUpload } from "../src/app/research/evidence/evidence-upload.mjs";

const baseline = JSON.parse(await readFile(new URL("../tools/shots/fixtures/material-bodies-baseline.json", import.meta.url), "utf8"));
const formOf = (patch) => { const c = { ...VALID, ...patch }; return { file: c.file ? { name: c.file.name, type: c.file.mimeType } : null, title: c.title, sourceUrl: c.url, publishedAt: c.published, reason: c.reason, stars: c.stars, impact: c.impact }; };

for (const [name, patch] of CASES) {
  test(`upload case ${name}: the rules answer as the old form did`, () => {
    const old = baseline.uploadRules[name];
    assert.ok(old, `no baseline for ${name}`);
    const form = formOf(patch);
    const errors = validateUpload(form);
    assert.equal(Object.keys(errors).length === 0, old.submitEnabled, JSON.stringify(errors));
    if (!old.submitEnabled) return;
    const sent = uploadInput({ ...form, file: { name: form.file.name }, stars: form.stars, impact: form.impact });
    assert.equal(sent.title, old.fields.title);
    assert.equal(sent.sourceUrl, old.fields.source_url);
    assert.equal(sent.publishedAt, old.fields.published_at);
    assert.equal(String(sent.credibilityStars), old.fields.credibility_stars);
    assert.equal(sent.credibilityReason, old.fields.credibility_reason);
    assert.equal(sent.impactSeverity, old.fields.impact_severity);
  });
}

test("the form's limits and the file filter are the old ones", () => {
  assert.equal(TITLE_MAX, baseline.uploadRules.attributes.titleMax);
  assert.equal(REASON_MAX, baseline.uploadRules.attributes.reasonMax);
  assert.equal(FILE_ACCEPT, baseline.uploadRules.attributes.accept);
});

test("a refused form names its fields in reading order", () => {
  const errors = validateUpload({ file: null, title: "", sourceUrl: "http://x.y", publishedAt: "", reason: "" });
  assert.deepEqual(Object.keys(errors).sort(), [...FIELD_ORDER].sort());
  assert.equal(errors.sourceUrl, "not-https");
  assert.equal(firstInvalid(errors), "file");
  assert.equal(firstInvalid({ reason: "missing", title: "missing" }), "title");
  assert.equal(firstInvalid({}), null);
  assert.equal(validateUpload({ ...formOf({}), sourceUrl: "" }).sourceUrl, "missing");
});

test("https is the only address kind", () => {
  assert.equal(isHttpsUrl("https://a.b"), true);
  assert.equal(isHttpsUrl(" https://a.b "), true);
  for (const bad of ["http://a.b", "ftp://a.b", "a.b", "", "javascript:alert(1)"]) assert.equal(isHttpsUrl(bad), false, bad);
  assert.equal(isAllowedEvidenceFile({ name: "A.PDF", type: "" }), true);
  assert.equal(isAllowedEvidenceFile({ name: "a.exe", type: "" }), false);
});
