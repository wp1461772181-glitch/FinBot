// ReportBot · page lines (design 6.5): four lines of different lengths on the right; fill 0.5 s each; a margin mark per unit (four to a page, then the
// page turns); a tick per marked line 120 ms apart; a reading underline; the four lines merge into one on done; one line is cut on error.
import test from "node:test";
import assert from "node:assert/strict";
import { AURAS } from "../src/aura/index.mjs";
import { R, forms, input, units, byKey } from "./aura-helpers.mjs";

const P = AURAS["page-lines"];
const lines = prims => prims.filter(p => /^line-\d/.test(p.key) && !p.key.endsWith("b"));
const marks = prims => prims.filter(p => p.key.startsWith("mark-"));
const checks = prims => prims.filter(p => p.key.startsWith("check-"));
const len = p => Math.abs(p.x2 - p.x1);

test("at rest: four faint lines of different lengths on the right of the body", () => {
  const out = P(input("idle"));
  assert.equal(out.length, 4);
  assert.ok(out.every(p => p.x1 > R && p.tone === 0 && p.opacity <= 0.5));
  assert.equal(new Set(out.map(len)).size, 4);
  assert.deepEqual(P(input("think")), []);
});

test("tool: the lines fill from left to right one after another, 0.5 s each", () => {
  const full = Object.fromEntries(lines(P(input("tool", { t: 9, units: 0 }))).map(p => [p.key, len(p)]));
  const filled = t => Object.fromEntries(lines(P(input("tool", { t, units: 0 }))).map(p => [p.key, Math.round((len(p) / full[p.key]) * 100) / 100]));
  assert.deepEqual(filled(0.25), { "line-0": 0.5 });
  assert.deepEqual(filled(0.75), { "line-0": 1, "line-1": 0.5 });
  assert.deepEqual(filled(1.6), { "line-0": 1, "line-1": 1, "line-2": 1, "line-3": 0.2 });
  assert.equal(Object.keys(filled(9)).length, 4);
  assert.equal(P(input("tool", { t: 0.25, units: 0 })).filter(p => p.key.startsWith("ground-")).length, 4, "the unfilled rest stays as a faint ground");
});

test("a margin mark (a small square) appears left of the line of each unit, four to a page", () => {
  const out = P(input("tool", { units: 3, t: 3 }));
  assert.equal(marks(out).length, 3);
  assert.ok(marks(out).every(p => p.kind === "rect" && p.cx === undefined && p.x < R * 1.15 && p.tone === 2 && p.unit !== undefined));
  assert.deepEqual(marks(out).map(p => p.unit), [0, 1, 2]);
  assert.equal(marks(P(input("tool", { units: 4, t: 3 }))).length, 4);
});

test("a fifth unit turns the page: the old page slides up and fades, a new page comes in with one mark", () => {
  const turning = P(input("tool", { units: 5, t: 3, ages: [9, 9, 9, 9, 0.1] }));
  assert.ok(turning.some(p => p.key.includes("old")), "the old page is still there, leaving");
  assert.equal(units(turning).length, 1, "the new page has one mark");
  const old = turning.find(p => p.key.startsWith("mark-old"));
  assert.ok(old.y < -0.1 * R * 0.0 + 100 && old.opacity < 1 && old.unit === undefined);
  const settled = P(input("tool", { units: 5, t: 3, ages: [9, 9, 9, 9, 1] }));
  assert.ok(!settled.some(p => p.key.includes("old")), "turned");
  assert.equal(marks(settled).length, 1);
  assert.equal(marks(P(input("tool", { units: 8, t: 3 }))).length, 4, "the second page is full");
  assert.equal(marks(P(input("tool", { units: 9, t: 3, ages: [9, 9, 9, 9, 9, 9, 9, 9, 9] }))).length, 1, "the third page");
});

test("check: a tick is drawn at the end of each marked line, one after another, 120 ms apart", () => {
  const out = t => checks(P(input("verify", { units: 3, t })));
  assert.equal(out(0.05).length, 1);
  assert.equal(out(0.15).length, 2);
  assert.equal(out(0.3).length, 3);
  const d = t => out(t)[0].d;
  assert.notEqual(d(0.04), d(0.2), "drawn progressively");
  assert.equal(d(0.5), d(2));
  const row = byKey(P(input("verify", { units: 3, t: 1 })), "line-1"), tick = byKey(P(input("verify", { units: 3, t: 1 })), "check-1");
  assert.match(tick.d, /^M [-\d.]+ [-\d.]+ L/);
  assert.ok(Number(tick.d.split(" ")[1]) > row.x2, "at the end of the line");
  assert.equal(checks(P(input("answer", { units: 3, verified: true }))).length, 3, "kept after the check");
  assert.equal(checks(P(input("answer", { units: 3, verified: false }))).length, 0);
  assert.equal(checks(P(input("hold", { units: 2, verified: true }))).length, 2);
});

test("output: a short underline goes down the lines one by one", () => {
  const under = t => byKey(P(input("answer", { t })), "reading");
  assert.ok(under(0).y1 < under(0.7).y1 && under(0.7).y1 < under(1.3).y1 && under(1.3).y1 < under(1.9).y1, "down, row by row");
  assert.ok(under(0).x2 - under(0).x1 < 0.4 * R, "short");
  assert.equal(under(0).y1, under(0.5).y1, "a step, then rest");
});

test("done: the four lines slide to the middle and become one thick line, a beat, then it fades", () => {
  const ys = t => lines(P(input("done", { units: 2, t }))).map(p => p.y1);
  assert.ok(ys(0.2).every(y => Math.abs(y) < Math.abs(ys(0)[0] ?? 999) + 1), "moving to the middle");
  const closed = P(input("done", { t: 0.5 }));
  assert.deepEqual([closed.length, closed[0].form, closed[0].y1, closed[0].w > 0.1 * R], [1, "closed", 0, true]);
  assert.equal(P(input("done", { t: 0.7 }))[0].opacity, 1, "a beat");
  assert.ok(P(input("done", { t: 1.05 }))[0].opacity < 1);
});

test("partial: the thick line has a gap in the middle", () => {
  const p = P(input("partial", { t: 0.5 }));
  assert.equal(p.length, 2);
  assert.equal(forms(p)[0], "gap");
  assert.ok(p[1].x1 - p[0].x2 > 0.1 * R);
});

test("error: one line is cut in the middle (data missing), in red; the others stay", () => {
  const out = P(input("error", { units: 2, t: 0.8 }));
  const pieces = out.filter(p => p.key.startsWith("line-1"));
  assert.equal(pieces.length, 2);
  assert.ok(pieces.every(p => p.tone === "danger"));
  assert.ok(pieces[1].x1 - pieces[0].x2 > 0.05 * R, "a gap");
  assert.equal(forms(out).length, 1);
  assert.equal(out.filter(p => /^line-[023]$/.test(p.key)).length, 3);
  assert.equal(checks(out).length, 0, "no ticks on a failed check");
});

test("forms: margin ticks (short stubs) and underline (equal thin lines) keep the grammar", () => {
  const stubs = AURAS["margin-ticks"](input("tool", { t: 9 })), thin = AURAS.underline(input("tool", { t: 9 }));
  assert.ok(lines(stubs).every(p => len(p) <= 0.21 * R));
  assert.equal(new Set(lines(thin).map(len)).size, 1);
  assert.ok(lines(thin)[0].w < lines(P(input("tool", { t: 9 })))[0].w);
  for (const form of ["margin-ticks", "underline"]) { assert.equal(AURAS[form](input("done", { t: 0.5 }))[0].form, "closed"); assert.equal(units(AURAS[form](input("tool", { units: 3 }))).length, 3); }
});

test("M: three lines and at most three marks, no page turn", () => {
  const out = P(input("tool", { tier: "M", units: 9, t: 9 }));
  assert.equal(lines(out).length, 3);
  assert.equal(units(out).length, 3);
});
