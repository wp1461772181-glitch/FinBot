import assert from "node:assert/strict";
import test from "node:test";
import { candidateGroupId, candidateGroups, canContinue, detailSection, modelChangedIds, pickedSources, reviseGate, reviseTarget, revisionRefs, sourceDiff, sourceDisabled, targetExpired, toggleSource, versionMethod } from "../src/forecast-detail.mjs";

const opt = (n, revisionType, over = {}) => ({ key: `official_filing:${n}`, source_type: "official_filing", source_id: `id-${n}`, label: `m${n}`, revisionType, ...over });

test("the bottom tab comes from the address; the old #revisions address (versions) and anything unknown are the first tab", () => {
  assert.equal(detailSection("versions"), "versions");
  assert.equal(detailSection("evaluation"), "evaluation");
  assert.equal(detailSection("audit"), "audit");
  assert.equal(detailSection(null), "versions");
  assert.equal(detailSection("nonsense"), "versions");
});

test("a version without a parent is the initial one; revisions say how they began", () => {
  assert.deepEqual(versionMethod({ parent_version_id: null, trigger_type: "manual_revision" }), { key: "initial", phrase: "初始" });
  assert.equal(versionMethod({ parent_version_id: "p", trigger_type: "manual_revision" }).phrase, "人工修订");
  assert.equal(versionMethod({ parent_version_id: "p", trigger_type: "automatic_monitor" }).phrase, "新材料修订");
  assert.equal(versionMethod({ parent_version_id: "p", trigger_type: "new_forecast" }).key, "update");
});

test("the source diff counts added, replaced, removed and inherited against the parent", () => {
  const item = (id, ev) => ({ source_type: "official_filing", source_id: id, event_version_id: ev });
  const parent = { evidence_version_manifest: [item("a", "1"), item("b", "2"), item("c", "3")] };
  const current = { evidence_version_manifest: [item("a", "1"), item("b", "9"), item("d", "4")] };
  assert.deepEqual(sourceDiff(current, parent), { total: 3, added: 1, replaced: 1, removed: 1, inherited: 1, hasParent: true });
  assert.deepEqual(sourceDiff(current, null), { total: 3, added: 0, replaced: 0, removed: 0, inherited: 0, hasParent: false });
  assert.equal(sourceDiff({}, null).total, 0);
});

test("a target before today is expired; an unreadable one is neither, and both keep the revision shut with their own reason", () => {
  assert.equal(targetExpired("2026-11-12", "2026-11-13"), true);
  assert.equal(targetExpired("2026-11-13", "2026-11-13"), false);
  assert.equal(targetExpired(null, "2026-11-13"), null);
  assert.equal(targetExpired("soon", "2026-11-13"), null);
  assert.deepEqual(reviseGate("2026-12-31", "2026-11-13"), { allowed: true, reason: null });
  assert.deepEqual(reviseGate("2026-10-01", "2026-11-13"), { allowed: false, reason: "该预测的目标已到期，只能查看历史版本。" });
  assert.deepEqual(reviseGate(undefined, "2026-11-13"), { allowed: false, reason: "该预测的目标合同无效，只能查看历史版本。" });
});

test("a version is marked when its model differs from its parent's, and only when both are read", () => {
  const versions = [{ id: "v1", parent_version_id: null }, { id: "v2", parent_version_id: "v1" }, { id: "v3", parent_version_id: "v2" }];
  const details = new Map([["v1", { m: "a" }], ["v2", { m: "b" }]]);
  const changed = (current, parent) => current.m !== parent.m;
  assert.deepEqual([...modelChangedIds(versions, details, changed)], ["v2"]);
});

test("candidates are grouped new, backfilled (with the ones in the library before), reanalyzed, status; an empty group is left out", () => {
  const options = [opt(1, "backfilled"), opt(2, "new"), opt(3, "preexisting"), opt(4, "mystery"), opt(5, "reanalyzed")];
  assert.deepEqual(candidateGroups(options).map((group) => [group.id, group.items.map((item) => item.source_id)]), [["new", ["id-2"]], ["backfilled", ["id-1", "id-3"]], ["reanalyzed", ["id-5"]], ["status", ["id-4"]]]);
  assert.deepEqual(candidateGroups([opt(1, "new")]).map((group) => group.id), ["new"]);
  assert.equal(candidateGroupId("anything else"), "status");
});

test("ticking stops at the cap; a ticked box can always be unticked; boxes past the cap are disabled", () => {
  let keys = [];
  for (let n = 1; n <= 12; n += 1) keys = toggleSource(keys, `k${n}`);
  assert.equal(keys.length, 10);
  assert.deepEqual(keys, Array.from({ length: 10 }, (_, i) => `k${i + 1}`));
  assert.equal(sourceDisabled(keys, "k11"), true);
  assert.equal(sourceDisabled(keys, "k3"), false);
  assert.equal(toggleSource(keys, "k3").length, 9);
  assert.equal(sourceDisabled(toggleSource(keys, "k3"), "k11"), false);
});

test("the request refs follow the list's order, not the order of the clicks, and carry only the two fields", () => {
  const options = [opt(1, "backfilled"), opt(2, "new", { source_type: "uploaded_media" })];
  assert.deepEqual(revisionRefs(options, [options[1].key, options[0].key]), [{ source_type: "official_filing", source_id: "id-1" }, { source_type: "uploaded_media", source_id: "id-2" }]);
  assert.deepEqual(pickedSources(options, []), []);
});

test("?revise= finds a library filing to show; it is never a pick", () => {
  const options = [opt(1, "backfilled"), opt(2, "new", { source_type: "uploaded_media", source_id: "abc" })];
  assert.equal(reviseTarget(options, "id-1")?.key, options[0].key);
  assert.equal(reviseTarget(options, "abc"), null, "only a library filing matches");
  assert.equal(reviseTarget(options, null), null);
});

test("the drawer goes on from the materials step only with one to ten ticked", () => {
  assert.equal(canContinue("parent", { picked: 0 }), true);
  assert.equal(canContinue("materials", { picked: 0 }), false);
  assert.equal(canContinue("materials", { picked: 1 }), true);
  assert.equal(canContinue("materials", { picked: 10 }), true);
  assert.equal(canContinue("materials", { picked: 11 }), false);
  assert.equal(canContinue("confirm", { picked: 3 }), false);
});
