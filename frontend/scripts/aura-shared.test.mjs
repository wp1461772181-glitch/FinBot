// The grammar every aura shares (design 6.2): easings, the time skeleton, caps, tiers, the end beats.
import test from "node:test";
import assert from "node:assert/strict";
import { ARRIVE, END, TRANSITION, TONE_LEVELS, ease, endBeat, endLength, normalize, visibility, rowShare, closingArc, TAU } from "../src/aura/shared.mjs";
import { AURAS } from "../src/aura/index.mjs";
import { T } from "../src/bloub-timing.mjs";
import { readFileSync } from "node:fs";
import { input } from "./aura-helpers.mjs";

test("easings: smooth is 0 to 1, spring overshoots about 6 percent, step moves in four jumps", () => {
  for (const kind of ["smooth", "spring", "step"]) { assert.equal(ease(kind, 0), 0); assert.equal(ease(kind, 1), 1); assert.equal(ease(kind, -3), 0); assert.equal(ease(kind, 9), 1); }
  let peak = 0; for (let i = 0; i <= 1000; i++) peak = Math.max(peak, ease("spring", i / 1000));
  assert.ok(peak > 1.055 && peak < 1.065, `spring peak ${peak}`);
  assert.deepEqual([...new Set(Array.from({ length: 101 }, (_, i) => ease("step", i / 100)))], [0, 0.25, 0.5, 0.75, 1]);
  assert.equal(ease("nonsense", 0.5), ease("smooth", 0.5));
  assert.equal(ease("smooth", NaN), 0);
});

test("time skeleton: a transition is at most 320 ms, the end beats fit the director's done (1.4 s) and failed (2.0 s)", () => {
  assert.ok(TRANSITION <= 0.32 && ARRIVE <= 0.32);
  assert.ok(endLength("done") <= T.SUCCESS && endLength("partial") <= T.SUCCESS, `done ${endLength("done")}`);
  assert.ok(endLength("error") <= T.ERROR, `error ${endLength("error")}`);
  assert.ok(END.done.close <= 0.32 && END.error.close <= 0.4);
  assert.equal(endLength("tool"), 0);
});

test("the end beat keeps real time whatever the tempo: the same real second is at the same place for a calm and a fast bot", () => {
  const at = (tempo, real) => endBeat(normalize({ phase: "done", t: real * tempo, tempo, tier: "L" }, { cap: 4 }));
  for (const real of [0.1, 0.3, 0.6, 1.0]) { const a = at(0.8, real), b = at(1.25, real); assert.ok(Math.abs(a.p - b.p) < 1e-9 && Math.abs(a.fade - b.fade) < 1e-9 && a.over === b.over, `at ${real} s`); }
  assert.equal(at(0.8, 1.2).over, true);
  assert.equal(at(1.25, 0.2).over, false);
});

test("visibility eases from what the previous state left over at most a transition; cancel is immediate; reduced is the state's own", () => {
  const vis = (over) => visibility(normalize(input("tool", over), { cap: 5 }));
  assert.equal(vis({ t: 0, settled: { phase: "idle", units: 0, t: 5 } }), 0.5);
  assert.equal(vis({ t: TRANSITION, settled: { phase: "idle", units: 0, t: 5 } }), 1);
  assert.ok(vis({ t: 0.16, settled: { phase: "idle", units: 0, t: 5 } }) > 0.5);
  assert.equal(visibility(normalize(input("cancel", { t: 0, settled: { phase: "tool", units: 3, t: 4 } }), { cap: 5 })), 0);
  assert.equal(visibility(normalize(input("tool", { reduced: true, settled: { phase: "idle" } }), { cap: 5 })), 1);
});

test("normalize: units are capped, M caps lower, resting states show no evidence, bad input is safe", () => {
  assert.equal(normalize(input("tool", { units: 99 }), { cap: 5, capM: 3 }).n, 5);
  assert.equal(normalize(input("tool", { units: 99, tier: "M" }), { cap: 5, capM: 3 }).n, 3);
  assert.equal(normalize(input("idle", { units: 4 }), { cap: 5 }).n, 0);
  assert.equal(normalize(input("tool", { units: -2 }), { cap: 5 }).n, 0);
  assert.equal(normalize(input("tool", { units: "x" }), { cap: 5 }).n, 0);
  assert.equal(normalize(input("tool", { tier: "S" }), { cap: 5 }).tier, null);
  assert.equal(normalize({ phase: "wat" }, { cap: 5 }).phase, "idle");
  assert.equal(normalize(undefined, { cap: 5 }).tier, null);
});

test("XS and S have no aura at all", () => {
  for (const [name, aura] of Object.entries(AURAS)) for (const tier of ["XS", "S", undefined, "xl"]) assert.deepEqual(aura(input("tool", { tier })), [], `${name} ${tier}`);
});

test("tones are the three steps of the thinking ring's brightness", () => {
  assert.deepEqual(TONE_LEVELS, [0.34, 0.66, 1]);
  const painter = readFileSync(new URL("../src/components/bot/bot-painter.ts", import.meta.url), "utf8");
  assert.match(painter, /RING_LEVELS\s*=\s*TONE_LEVELS/, "the thinking rings and the aura read the same three levels");
});

test("rowShare and closingArc: the shares tile the line / the circle", () => {
  const shares = [0, 1, 2].map(i => rowShare(i, 3));
  assert.equal(shares[0][0], -0.9); assert.ok(Math.abs(shares[2][1] - 0.9) < 1e-9); assert.ok(Math.abs(shares[0][1] - shares[1][0]) < 1e-9);
  assert.ok(Math.abs(rowShare(0, 1, true)[1] - 0.6) < 1e-9, "a gap leaves the end open");
  const [c, hw] = closingArc(1, 4, 1, 0.01, 1); assert.ok(Math.abs(c - TAU * 0.375) < 1e-9 && Math.abs(hw - TAU / 8) < 1e-9);
  const [c0] = closingArc(1, 4, 1, 0.01, 0); assert.equal(c0, 1);
});
