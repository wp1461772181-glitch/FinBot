import assert from "node:assert/strict";
import test from "node:test";
import { archivedCurrent, dayLabel, hasAnyView, splitVersions, statusPhrase, versionSpan } from "../src/owner-views.mjs";

const v = (id, status, created_at, ended_at = null) => ({ id, status, created_at, ended_at, text: id, quote: id });

test("the active version is split from the earlier ones, newest first, whatever order they arrive in", () => {
  const { active, earlier } = splitVersions([v("old", "superseded", "2026-11-01T02:00:00Z", "2026-11-08T02:00:00Z"), v("now", "active", "2026-11-08T02:00:00Z"), v("gone", "dropped", "2026-10-01T02:00:00Z", "2026-10-20T02:00:00Z")]);
  assert.equal(active.id, "now");
  assert.deepEqual(earlier.map(x => x.id), ["old", "gone"]);
});

test("no view and no history means no card; only history still has one (with no current view)", () => {
  assert.equal(hasAnyView([]), false);
  assert.equal(hasAnyView(null), false);
  assert.equal(hasAnyView([v("a", "dropped", "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z")]), true);
  assert.equal(splitVersions([v("a", "dropped", "2026-10-01T00:00:00Z")]).active, null);
});

test("status phrases are 已更新 and 已撤回; the active one has none", () => {
  assert.equal(statusPhrase("superseded"), "已更新");
  assert.equal(statusPhrase("dropped"), "已撤回");
  assert.equal(statusPhrase("active"), "");
});

test("dates are the owner's Beijing day: 11月8日, or 11/8 in English; a bad value is empty", () => {
  assert.equal(dayLabel("2026-11-07T17:00:00Z"), "11月8日");
  assert.equal(dayLabel("2026-11-07T17:00:00Z", "en-US"), "11/8");
  assert.equal(dayLabel("not a date"), "");
  assert.equal(dayLabel(null), "");
});

test("an earlier version's span runs from the day said to the day it ended", () => {
  assert.equal(versionSpan(v("a", "superseded", "2026-11-01T02:00:00Z", "2026-11-08T02:00:00Z")), "11月1日 – 11月8日");
  assert.equal(versionSpan(v("a", "dropped", "2026-11-01T02:00:00Z")), "11月1日");
});

test("an archived view is the card's current one only when no view is active; 已归档 is its status phrase", () => {
  assert.equal(statusPhrase("archived"), "已归档");
  const archived = v("arch", "archived", "2026-11-01T02:00:00Z", "2026-11-20T02:00:00Z");
  assert.equal(archivedCurrent([v("old", "dropped", "2026-10-01T02:00:00Z", "2026-10-20T02:00:00Z"), archived]).id, "arch");
  assert.equal(archivedCurrent([archived, v("new", "active", "2026-11-22T02:00:00Z")]), null);
  assert.equal(archivedCurrent([v("new", "active", "2026-11-22T02:00:00Z"), v("a", "archived", "2026-11-01T02:00:00Z")]), null);
  assert.equal(archivedCurrent([v("d", "dropped", "2026-11-01T02:00:00Z"), v("a", "archived", "2026-10-01T02:00:00Z")]), null);
  assert.equal(archivedCurrent(null), null);
});
