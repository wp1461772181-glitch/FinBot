import assert from "node:assert/strict";
import test from "node:test";
import { archivedCurrent, basisLine, dayLabel, hasAnyView, reviewOf, splitVersions, statusPhrase, strayFigures, verdictBadge, versionSpan } from "../src/owner-views.mjs";

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

test("a review with no text is no review; one with text is returned as the server sent it", () => {
  assert.equal(reviewOf({}), null);
  assert.equal(reviewOf({ review: null }), null);
  assert.equal(reviewOf({ review: { verdict: "held", text: "  " } }), null);
  const review = { verdict: "held", verdict_label: "成立", text: "涨了。", unmatched_figures: [], basis: null, created_at: null };
  assert.equal(reviewOf({ review }), review);
});

test("the five verdicts have their words and tone; an unknown one shows the server's label, neutral", () => {
  assert.deepEqual(verdictBadge({ verdict: "held" }), { label: "成立", kind: "success" });
  assert.deepEqual(verdictBadge({ verdict: "not_held" }), { label: "没有成立", kind: "failure" });
  assert.deepEqual(verdictBadge({ verdict: "mixed" }), { label: "部分成立", kind: "neutral" });
  assert.deepEqual(verdictBadge({ verdict: "too_early" }), { label: "还早", kind: "neutral" });
  assert.deepEqual(verdictBadge({ verdict: "unclear" }), { label: "说不准", kind: "neutral" });
  assert.deepEqual(verdictBadge({ verdict: "new_one", verdict_label: "别的" }), { label: "别的", kind: "neutral" });
});

test("the basis line is made of what the code has; a missing part is left out, never invented", () => {
  const both = { price_then: { date: "2026-08-01", close: 100 }, price_now: { date: "2026-11-24", close: 112.34 }, change_pct: 12.345, quarter_label: "FY2027 Q2" };
  assert.equal(basisLine(both), "说的时候 $100.00 → 现在 $112.34（+12.3%） · 最新一季 FY2027 Q2");
  assert.equal(basisLine({ ...both, change_pct: -4 }), "说的时候 $100.00 → 现在 $112.34（-4.0%） · 最新一季 FY2027 Q2");
  assert.equal(basisLine({ ...both, change_pct: null, quarter_label: null }), "说的时候 $100.00 → 现在 $112.34");
  assert.equal(basisLine({ price_then: null, price_now: { close: 50 }, quarter_label: "FY2027 Q2" }), "现在 $50.00 · 最新一季 FY2027 Q2");
  assert.equal(basisLine({ price_then: { close: 50 } }), "说的时候 $50.00");
  assert.equal(basisLine({ quarter_label: "FY2027 Q2" }), "最新一季 FY2027 Q2");
  assert.equal(basisLine({ price_then: null, price_now: null, change_pct: null, quarter_label: null }), "");
  assert.equal(basisLine(null), "");
  assert.equal(basisLine(both, { then: "when said", now: "now", quarter: "latest quarter" }), "when said $100.00 → now $112.34（+12.3%） · latest quarter FY2027 Q2");
});

test("stray figures are listed only when there are some", () => {
  assert.deepEqual(strayFigures({ unmatched_figures: ["37%", " ", "$12"] }), ["37%", "$12"]);
  assert.deepEqual(strayFigures({ unmatched_figures: [] }), []);
  assert.deepEqual(strayFigures({}), []);
  assert.deepEqual(strayFigures(null), []);
});
