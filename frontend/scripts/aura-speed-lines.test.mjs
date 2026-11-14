// TeslaBot · speed lines (design 6.5): three lines behind on the left, a solid trail segment per unit (five at most), checked left to right,
// drawn back in and merged into one line under the body when done, dashed and drooping 12 degrees when it fails.
import test from "node:test";
import assert from "node:assert/strict";
import { AURAS } from "../src/aura/index.mjs";
import { R, deg, forms, input, units, byKey } from "./aura-helpers.mjs";

const flow = prims => prims.filter(p => p.key.startsWith("flow-"));
const trail = prims => prims.filter(p => p.key.startsWith("trail-"));
const len = p => Math.hypot(p.x2 - p.x1, p.y2 - p.y1);

test("three horizontal lines on the left, 0.4 R to 0.8 R long; at rest short and almost invisible", () => {
  const out = flow(AURAS["speed-lines"](input("tool", { t: 1 })));
  assert.equal(out.length, 3);
  assert.deepEqual(out.map(p => Math.round(len(p) / R * 100) / 100), [0.4, 0.8, 0.55]);
  assert.ok(out.every(p => p.y1 === p.y2 && p.x1 < -R && p.x2 < p.x1), "level, behind (left of) the body");
  const rest = AURAS["speed-lines"](input("idle"));
  assert.equal(rest.length, 3);
  assert.ok(rest.every(p => p.opacity <= 0.5 && len(p) < 0.5 * R));
  assert.deepEqual(AURAS["speed-lines"](input("think")), []);
});

test("tool: the lines shoot out (spring: a little past full length) and flow backwards; a solid segment is left per unit, five at most", () => {
  const at = t => flow(AURAS["speed-lines"](input("tool", { t, settled: { phase: "idle", units: 0, t: 3 }, easing: "spring" })))[1];
  assert.ok(len(at(0)) < len(at(0.32)));
  const peak = Math.max(...Array.from({ length: 33 }, (_, i) => len(at(i * 0.01))));
  assert.ok(peak > 0.8 * R * 1.02 && peak < 0.8 * R * 1.04, `overshoot ${peak / (0.8 * R)}`); // 6% of the way from half to full length
  const flowing = (t) => flow(AURAS["speed-lines"](input("tool", { t })))[0].dashOffset;
  assert.ok(flowing(1) < flowing(0.5), "the dashes run away from the body (offset falls)");
  const t3 = trail(AURAS["speed-lines"](input("tool", { units: 3 })));
  assert.equal(t3.length, 3);
  assert.ok(t3.every(p => p.tone === 2 && p.opacity === 1 && !p.dash));
  assert.ok(t3[0].x1 < t3[1].x1 && t3[1].x1 < t3[2].x1, "the oldest is furthest left");
  assert.equal(trail(AURAS["speed-lines"](input("tool", { units: 9 }))).length, 5);
});

test("check: the solid segments light from left to right", () => {
  const widths = t => trail(AURAS["speed-lines"](input("verify", { units: 3, t }))).map(p => p.w);
  const base = widths(1.0);
  assert.ok(base.every(w => w === base[0]));
  for (let i = 0; i < 3; i++) assert.ok(widths(0.1 * i + 0.1)[i] > base[i] * 1.5, `segment ${i}`);
  assert.ok(widths(0.1)[2] === base[2], "the third is not lit yet");
});

test("output: the lines hold at six tenths and keep flowing; waiting: they are drawn in, the trail stays", () => {
  const l = flow(AURAS["speed-lines"](input("answer", { t: 5 })));
  assert.deepEqual(l.map(p => Math.round(len(p) / R * 100) / 100), [0.24, 0.48, 0.33], "60% of the full lengths");
  assert.ok(l[0].dash, "flowing");
  assert.equal(flow(AURAS["speed-lines"](input("hold", { t: 5 }))).length, 0);
  assert.equal(trail(AURAS["speed-lines"](input("hold", { t: 5, units: 2 }))).length, 2);
});

test("done: the lines draw back, the trail joins into one line under the body (a closed form), then it fades", () => {
  const mid = AURAS["speed-lines"](input("done", { t: 0.16 }));
  assert.ok(flow(mid).every((p, j) => len(p) < [0.4, 0.8, 0.55][j] * R * 0.6), "drawing back in");
  const closed = AURAS["speed-lines"](input("done", { t: 0.5 }));
  assert.equal(closed.length, 1);
  const line = closed[0];
  assert.deepEqual([line.form, line.y1 === line.y2, line.y1 > R], ["closed", true, true], "one level line under the body");
  assert.ok(line.x1 < 0 && line.x2 > 0);
  assert.equal(AURAS["speed-lines"](input("done", { t: 0.9 }))[0].opacity < 1, true);
  assert.deepEqual(AURAS["speed-lines"](input("done", { t: 1.2 })), []);
});

test("partial: the merged line stops short and leaves an open end", () => {
  const p = AURAS["speed-lines"](input("partial", { t: 0.5 }));
  assert.equal(forms(p)[0], "gap");
  assert.ok(p.some(x => x.kind === "dot"), "the missing part is marked");
  assert.ok(byKey(p, "merged").x2 < 0.7 * R);
});

test("error: the lines turn dashed and droop 12 degrees, the trail's segments too, in red", () => {
  const out = AURAS["speed-lines"](input("error", { t: 0.8 }));
  const lines = flow(out);
  assert.ok(lines.every(p => p.dash && p.tone === "danger"));
  for (const p of lines) assert.ok(Math.abs(deg(Math.atan2(p.y2 - p.y1, p.x1 - p.x2)) - 12) < 0.01, "12 degrees down at the far end");
  assert.ok(trail(out).every(p => p.dash && p.tone === "danger" && p.y2 > p.y1));
  assert.equal(forms(out).length, 1);
  assert.ok(AURAS["speed-lines"](input("error", { t: 0.2 })).length === out.length, "it droops, it does not shake: the same nodes");
  const early = flow(AURAS["speed-lines"](input("error", { t: 0.1 })))[0], late = flow(out)[0];
  assert.ok(late.y2 > early.y2, "the droop grows to its end");
});

test("M: three lines and at most three trail segments", () => {
  const out = AURAS["speed-lines"](input("tool", { tier: "M", units: 9 }));
  assert.equal(flow(out).length, 3);
  assert.equal(units(out).length, 3);
});
