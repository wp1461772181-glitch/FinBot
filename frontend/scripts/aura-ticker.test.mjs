// NewsBot · the ticker and the signal arcs (design 6.5): five bars below at 1.35 R and two arcs at the upper right; everything in steps.
import test from "node:test";
import assert from "node:assert/strict";
import { AURAS } from "../src/aura/index.mjs";
import { R, forms, input, units, byKey } from "./aura-helpers.mjs";

const T = AURAS.ticker;
const bars = prims => prims.filter(p => p.key.startsWith("bar-"));
const arcs = prims => prims.filter(p => p.key.startsWith("arc-"));
const midX = p => (p.kind === "line" ? (p.x1 + p.x2) / 2 : p.cx);
const lens = prims => bars(prims).map(p => Math.round(Math.abs(p.x2 - p.x1)));

test("at rest: five bars of different lengths 1.35 R below and two arcs at the upper right, all faint", () => {
  const out = T(input("idle"));
  assert.equal(bars(out).length, 5);
  assert.equal(arcs(out).length, 2);
  assert.ok(bars(out).every(p => Math.abs(p.y1 - 1.35 * R) < 0.01));
  assert.equal(new Set(lens(out)).size, 5, "five different lengths");
  assert.ok(arcs(out).every(p => p.cx > 0 && p.cy < 0), "upper right");
  assert.ok(out.every(p => p.tone === 0 || p.opacity <= 0.9));
});

test("think: the two arcs light in turn (a step every half second), the bars are hidden", () => {
  const lit = t => arcs(T(input("think", { t }))).map(p => p.tone);
  assert.deepEqual(lit(0.1), [2, 0]); assert.deepEqual(lit(0.6), [0, 2]); assert.deepEqual(lit(1.1), [2, 0]);
  assert.equal(bars(T(input("think"))).length, 0);
});

test("tool: the bars crawl right to left one slot at a time; a unit cuts a bar: solid, parked at the far left (five at most)", () => {
  const free = t => bars(T(input("tool", { units: 0, t }))).map(midX);
  assert.deepEqual(free(0.05), free(0.2), "no move inside a step");
  assert.notDeepEqual(free(0.05), free(0.4), "a step every third of a second");
  const out = T(input("tool", { units: 2, t: 0.5 }));
  const parked = bars(out).filter(p => p.unit !== undefined);
  assert.equal(parked.length, 2);
  assert.ok(parked.every(p => p.tone === 2) && bars(out).filter(p => p.unit === undefined).every(p => p.tone === 1));
  const slots = parked.map(midX), pitch = 0.46 * R;
  assert.ok(Math.abs(slots[0] + 2 * pitch) < 0.01 && Math.abs(slots[1] + pitch) < 0.01, "the two leftmost slots");
  assert.equal(units(T(input("tool", { units: 12 }))).length, 5);
  // the crawl stays inside the free slots
  for (const t of [0, 0.4, 0.7, 1.1, 2]) for (const p of bars(T(input("tool", { units: 2, t }))).filter(q => q.unit === undefined)) assert.ok(midX(p) > -pitch + 0.5, `free bar at ${t}`);
  assert.ok(lens(out).every(Number.isFinite));
});

test("the crawl moves in steps: four jumps per move, never in between (step easing for the entry)", () => {
  const out = [0, 0.04, 0.08, 0.12, 0.16, 0.2, 0.24, 0.28, 0.32].map(t => arcs(T(input("tool", { t, easing: "step", settled: { phase: "think", units: 0, t: 2 } }))).map(p => p.opacity));
  assert.ok(new Set(out.flat().map(v => Math.round(v * 1000))).size <= 6, "few distinct levels: stepped");
});

test("check: a small dot lights above each parked bar in turn", () => {
  const dots = t => T(input("verify", { units: 3, t })).filter(p => p.key.startsWith("chk-")).map(p => p.key);
  assert.deepEqual(dots(0.1), ["chk-0"]); assert.deepEqual(dots(0.3), ["chk-0", "chk-1"]); assert.deepEqual(dots(0.5), ["chk-0", "chk-1", "chk-2"]);
  const above = T(input("verify", { units: 3, t: 1 })), bar = byKey(above, "bar-1"), dot = byKey(above, "chk-1");
  assert.ok(dot.cy < bar.y1 && Math.abs(dot.cx - midX(bar)) < 0.01);
  assert.equal(T(input("answer", { units: 3, verified: true })).filter(p => p.key.startsWith("chk-")).length, 3, "they stay once checked");
  assert.equal(T(input("answer", { units: 3, verified: false })).filter(p => p.key.startsWith("chk-")).length, 0, "no check, no marks");
});

test("output: the crawl goes on and the arcs are out; waiting: the crawl stops and both arcs stay lit", () => {
  assert.ok(arcs(T(input("answer"))).every(p => p.tone === 0 && p.opacity <= 0.6));
  const a = T(input("hold", { units: 2, t: 0.1 })), b = T(input("hold", { units: 2, t: 9 }));
  assert.deepEqual(a, b);
  assert.deepEqual(arcs(a).map(p => p.tone), [2, 2]);
});

test("done: the parked bars press into one thick line, which flashes one step, then fades", () => {
  const closed = T(input("done", { t: 0.34 }));
  const merged = byKey(closed, "merged");
  assert.equal(forms(closed)[0], "closed"); assert.equal(closed.filter(p => p.key.startsWith("bar-")).length, 0);
  assert.ok(merged.w > 0.1 * R, "a thick line");
  assert.ok(byKey(T(input("done", { t: 0.4 })), "merged").w > byKey(T(input("done", { t: 0.7 })), "merged").w, "a flash of one step");
  const fades = [0.7, 0.8, 0.9, 1.0].map(t => T(input("done", { t }))[0]?.opacity);
  assert.ok(fades.every((v, i) => i === 0 || v <= fades[i - 1]) && fades[3] < 1, "stepped fade");
  assert.ok(new Set(fades.map(v => Math.round(v * 100))).size <= 4);
  assert.deepEqual(T(input("done", { t: 1.2 })), []);
});

test("partial: the thick line stops short and leaves a gap", () => { assert.deepEqual(forms(T(input("partial", { t: 0.5 }))), ["gap"]); });

test("error: the outer arc goes out, the bars drop one after another", () => {
  const out = T(input("error", { t: 0.2, units: 2 }));
  assert.equal(arcs(out).length, 1, "the outer arc is gone, the inner one stays");
  assert.equal(arcs(out)[0].form, "broken");
  assert.ok(arcs(out)[0].tone === "danger");
  const y = (t, i) => byKey(T(input("error", { t, units: 2 })), `bar-${i}`)?.y1;
  assert.ok(y(0.3, 0) > 1.35 * R + 1 && Math.abs(y(0.3, 4) - 1.35 * R) < 0.5, "the first bar is falling while the last has not started");
  assert.equal(bars(T(input("error", { t: 1.6 }))).length, 0, "all of them are down");
  assert.equal(arcs(T(input("error", { t: 1.6 }))).length, 1, "the broken signal stays for the two seconds");
});

test("unread: the arcs flash twice (at most 3 a second); sleep: the arcs only carry the slow-blink mark (CSS does the blinking)", () => {
  const on = t => arcs(T(input("unread", { t }))).length > 0;
  assert.deepEqual([0.05, 0.25, 0.45, 0.65, 2].map(on), [true, false, true, false, false]);
  const sleep = T(input("sleep", { t: 4 }));
  assert.equal(sleep.length, 2);
  assert.ok(sleep.every(p => p.anim === "slow-blink"));
  assert.deepEqual(sleep, T(input("sleep", { t: 99 })), "no per-frame work");
  assert.deepEqual(T(input("offline")), []);
});

test("forms: morse (dashes and dots) and beacon (round dots on a curve) are the same grammar", () => {
  const morse = AURAS.morse(input("tool", { units: 2 })), beacon = AURAS.beacon(input("tool", { units: 2 }));
  assert.ok(bars(morse).some(p => p.kind === "line") && bars(morse).some(p => p.kind === "dot"));
  assert.ok(bars(beacon).every(p => p.kind === "dot"));
  assert.equal(units(morse).length, 2); assert.equal(units(beacon).length, 2);
  assert.equal(forms(AURAS.morse(input("done", { t: 0.5 })))[0], "closed");
  assert.ok(forms(AURAS.beacon(input("error", { t: 0.5 }))).includes("broken"));
});

test("M: three bars", () => { assert.equal(bars(T(input("idle", { tier: "M" }))).length, 3); assert.equal(units(T(input("tool", { tier: "M", units: 9 }))).length, 3); });
