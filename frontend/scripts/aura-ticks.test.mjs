// FinBot · the evidence dial (design 6.5): twelve ticks at 1.28 R; a point sweeps 1.6 s a lap; a tick lights per unit; the check flashes them 80 ms apart;
// the close joins the lit ticks into a whole ring; the break opens it at the bottom.
import test from "node:test";
import assert from "node:assert/strict";
import { AURAS } from "../src/aura/index.mjs";
import { ticks } from "../src/aura/ticks.mjs";
import { R, angleOf, byKey, centre, deg, forms, input, units } from "./aura-helpers.mjs";

const lit = prims => units(prims).filter(p => p.key.startsWith("slot-"));
const dist = p => Math.hypot(...centre(p));

test("at rest the ring is twelve faint ticks at 1.28 R, almost invisible (design 6.3)", () => {
  const prims = AURAS.ticks(input("idle"));
  assert.equal(prims.length, 12);
  assert.ok(prims.every(p => p.tone === 0 && p.opacity <= 0.55), "dim");
  for (const p of prims) assert.ok(Math.abs(dist(p) - 1.28 * R) < 0.5, "on the ring");
  assert.deepEqual(prims.map(p => Math.round(angleOf(...centre(p)))).sort((a, b) => a - b), Array.from({ length: 12 }, (_, i) => i * 30));
  assert.equal(AURAS.ticks(input("think")).length, 0, "while it thinks the thinking ring is the star: no aura");
});

test("tool: exactly one lit tick per unit, at 0, 30, 60 degrees; a point sweeps clockwise at 1.6 s a lap", () => {
  const prims = AURAS.ticks(input("tool", { units: 3, t: 0.4 }));
  const on = lit(prims);
  assert.equal(on.length, 3);
  assert.deepEqual(on.map(p => Math.round(angleOf(...centre(p)))), [0, 30, 60]);
  assert.ok(on.every(p => p.tone === 2 && p.opacity === 1));
  assert.equal(prims.filter(p => p.tone === 0).length, 9, "the other nine stay dim");
  const sweep = byKey(prims, "sweep");
  assert.ok(Math.abs(angleOf(sweep.cx, sweep.cy) - 90) < 0.5, "a quarter lap (0.4 s of 1.6 s) is 90 degrees clockwise");
  assert.ok(Math.abs(angleOf(...centre(byKey(AURAS.ticks(input("tool", { t: 0.8 })), "sweep"))) - 180) < 0.5);
  assert.ok(Math.abs(angleOf(...centre(byKey(AURAS.ticks(input("tool", { t: 1.6 + 0.4 })), "sweep"))) - 90) < 0.5, "a lap is 1.6 s");
  assert.equal(byKey(AURAS.ticks(input("verify", { t: 0.4 })), "sweep"), undefined, "the sweep is a collecting motion only");
});

test("a unit that has just come back arrives: longer and dimmer at first, then the lit tick of the others", () => {
  const fresh = lit(AURAS.ticks(input("tool", { units: 2, t: 2, ages: [9, 0.02] })));
  const len = p => Math.hypot(p.x2 - p.x1, p.y2 - p.y1);
  assert.ok(len(fresh[1]) > len(fresh[0]) && fresh[1].opacity < 1 && fresh[0].opacity === 1);
  const settled = lit(AURAS.ticks(input("tool", { units: 2, t: 2, ages: [9, 0.3] })));
  assert.ok(Math.abs(len(settled[1]) - len(settled[0])) < 0.01);
});

test("check: the lit ticks flash one after another, 80 ms apart (tick k peaks 80 ms after tick k-1)", () => {
  const length = (t, k) => { const p = lit(AURAS.ticks(input("verify", { units: 4, t })))[k]; return Math.hypot(p.x2 - p.x1, p.y2 - p.y1); };
  const steps = Array.from({ length: 41 }, (_, i) => i * 0.01);
  const peakAt = k => steps.reduce((best, t) => (length(t, k) > length(best, k) + 1e-9 ? t : best), 0);
  const peaks = [0, 1, 2, 3].map(peakAt);
  for (let k = 0; k < 4; k++) assert.ok(Math.abs(peaks[k] - (0.08 * k + 0.08)) < 0.011, `tick ${k} peaks at ${peaks[k]}`);
  assert.ok(length(0.08, 0) > length(1.0, 0) * 1.4, "the flash is visible");
  assert.equal(length(1.0, 0), length(1.0, 3), "between flashes all are alike");
});

test("output: the ring holds and breathes a little (no tick moves); waiting: it is still", () => {
  const radius = t => dist(lit(AURAS.ticks(input("answer", { t })))[0]);
  assert.ok(radius(0.625) > radius(0) && radius(0.625) < 1.28 * R * 1.02, "a breath of about one percent, every 2.5 s");
  assert.equal(radius(0), radius(2.5));
  const a = AURAS.ticks(input("hold", { t: 0.5 })), b = AURAS.ticks(input("hold", { t: 7.7 }));
  assert.deepEqual(a, b, "waiting for you: still");
  assert.equal(lit(a).length, 3);
});

test("done: the lit ticks stretch along the circle and meet: a closed ring at the end of 320 ms, a beat, then it fades; the unlit ticks are gone", () => {
  const mid = AURAS.ticks(input("done", { units: 3, t: 0.16 }));
  assert.equal(units(mid).length, 3);
  assert.ok(units(mid).every(p => p.kind === "arc"), "the ticks became arcs");
  assert.ok(mid.filter(p => !p.unit && p.unit !== 0).every(p => p.opacity < 1), "the unlit ticks are leaving");
  const spans = units(AURAS.ticks(input("done", { units: 3, t: 0.3 }))).map(p => p.a1 - p.a0);
  assert.ok(spans.every(s => s > 1.5), "nearly a third of a circle each");
  const closed = AURAS.ticks(input("done", { t: 0.32 }));
  assert.equal(closed.length, 1);
  assert.deepEqual([closed[0].kind, closed[0].form, closed[0].a0, Math.round(closed[0].a1 * 1000) / 1000, closed[0].r], ["arc", "closed", 0, Math.round(2 * Math.PI * 1000) / 1000, 1.28 * R]);
  assert.equal(AURAS.ticks(input("done", { t: 0.32 + 0.4 - 0.01 }))[0].opacity, 1, "it holds for 0.4 s");
  assert.ok(AURAS.ticks(input("done", { t: 1.0 }))[0].opacity < 0.5, "then it fades");
  assert.deepEqual(AURAS.ticks(input("done", { t: 1.2 })), []);
  assert.deepEqual(AURAS.ticks(input("done", { t: 0.5, units: 0 })), [], "a turn that brought nothing back closes nothing");
});

test("partial: it closes but one gap remains", () => {
  const p = AURAS.ticks(input("partial", { t: 0.5 }));
  assert.equal(p.length, 1);
  assert.equal(p[0].form, "gap");
  assert.ok(Math.abs(deg(p[0].a1 - p[0].a0) - 324) < 0.01, "a gap of 36 degrees");
});

test("error: the ring opens at the bottom: the tick at six o'clock is gone, its two neighbours fall and fade, the rest turn red", () => {
  const early = AURAS.ticks(input("error", { t: 0.1, units: 3 })), mid = AURAS.ticks(input("error", { t: 0.3, units: 3 })), late = AURAS.ticks(input("error", { t: 0.6, units: 3 }));
  const keys = prims => prims.map(p => p.key);
  assert.ok(!keys(early).includes("slot-6"), "the bottom tick is simply gone");
  assert.ok(keys(early).includes("slot-5") && keys(early).includes("slot-7"), "the neighbours are still there at first");
  const y = prims => centre(prims.find(p => p.key === "slot-5"))[1];
  assert.ok(y(mid) > y(early) + 0.5 && byKey(mid, "slot-5").opacity < byKey(early, "slot-5").opacity, "falling and fading");
  assert.ok(!keys(late).includes("slot-5") && !keys(late).includes("slot-7") && !keys(late).includes("slot-6"), "faded out");
  assert.equal(late.length, 9, "nine ticks remain");
  assert.ok(lit(late).every(p => p.tone === "danger"), "the lit ones are red");
  assert.equal(forms(late).length, 1);
  assert.equal(AURAS.ticks(input("error", { t: 1.6 })).length, 9, "the gap holds for two seconds");
  // the gap is at the bottom: none of the ticks that remain is near six o'clock
  assert.ok(late.every(p => { const a = angleOf(...centre(p)); return Math.abs(a - 180) > 29; }));
});

test("M tier: eight slots, at most five lit, no sweep flash detail; gauge and pips are the same grammar in other shapes", () => {
  assert.equal(AURAS.ticks(input("idle", { tier: "M" })).length, 8);
  assert.equal(lit(AURAS.ticks(input("tool", { tier: "M", units: 12 }))).length, 5);
  assert.equal(AURAS.gauge(input("idle")).length, 10);
  assert.equal(AURAS.pips(input("idle")).length, 12);
  assert.ok(AURAS.pips(input("tool", { units: 2 })).every(p => p.kind === "dot" || p.key === "sweep"));
  assert.ok(AURAS.gauge(input("tool", { units: 2 })).filter(p => p.kind === "arc" && p.key.startsWith("slot")).length === 10);
  // a gauge is three quarters of a circle: open at the bottom, always
  const angles = AURAS.gauge(input("idle")).map(p => angleOf(...centre(p)));
  assert.ok(angles.every(a => a > 224 || a < 136), "nothing in the bottom opening");
  for (const form of ["gauge", "pips"]) {
    assert.equal(ticks(input("done", { t: 0.5 }), form)[0].form, "closed");
    assert.ok(ticks(input("error", { t: 0.8 }), form).some(p => p.form === "broken"));
  }
  assert.equal(ticks(input("tool"), "nonsense").length, ticks(input("tool"), "ticks").length, "an unknown form is the dial");
});
