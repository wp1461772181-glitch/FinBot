// The generalist's dots and the tracker's reticle (design 6.5): the two plainest auras, each complete in all four beats.
import test from "node:test";
import assert from "node:assert/strict";
import { AURAS } from "../src/aura/index.mjs";
import { R, angleOf, centre, forms, input, units, byKey, deg } from "./aura-helpers.mjs";

const D = AURAS["orbit-dots"], Rt = AURAS.reticle;
const dots = prims => prims.filter(p => p.key.startsWith("dot-"));

test("dots: three faint dots at rest; one lights per unit (a fourth, fifth, sixth join when there are more); they turn while working", () => {
  assert.equal(D(input("idle")).length, 3);
  assert.ok(D(input("idle")).every(p => p.tone === 0));
  const two = dots(D(input("tool", { units: 2 })));
  assert.deepEqual(two.map(p => p.tone), [2, 2, 0]);
  assert.equal(dots(D(input("tool", { units: 5 }))).length, 5);
  assert.equal(dots(D(input("tool", { units: 99 }))).length, 6);
  assert.equal(units(D(input("tool", { units: 2 }))).length, 2);
  const a = angleOf(...centre(dots(D(input("tool", { units: 3, t: 0 })))[0])), b = angleOf(...centre(dots(D(input("tool", { units: 3, t: 0.8 })))[0]));
  assert.ok(Math.abs(b - a - 90) < 0.5, "a quarter turn in 0.8 s: 3.2 s a lap");
  assert.deepEqual(D(input("think")), []);
});

test("dots: the lit ones flash in turn on the check, join into one ring on done, and one lets go on error", () => {
  const rad = (t, k) => dots(D(input("verify", { units: 3, t })))[k].r;
  assert.ok(rad(0.1, 0) > rad(1.1, 0) * 1.3 && rad(0.22, 1) > rad(1.1, 1) * 1.3 && rad(0.34, 2) > rad(1.1, 2) * 1.3, "each at its own moment, 120 ms apart");
  assert.ok(rad(0.1, 1) <= rad(1.1, 1) * 1.001 && rad(0.22, 0) <= rad(1.1, 0) * 1.5, "and not before it");
  const mid = D(input("done", { units: 3, t: 0.16 }));
  assert.ok(units(mid).every(p => p.kind === "arc"));
  const closed = D(input("done", { units: 3, t: 0.4 }));
  assert.deepEqual([closed.length, closed[0].form, closed[0].r], [1, "closed", 1.3 * R]);
  assert.equal(forms(D(input("partial", { t: 0.4 })))[0], "gap");
  const err = D(input("error", { units: 3, t: 0.3 }));
  assert.ok(err.every(p => p.tone === "danger") && forms(err).length === 1);
  const y = t => centre(dots(D(input("error", { units: 3, t })))[2])[1];
  assert.ok(y(0.3) > y(0.05), "the last dot falls");
});

test("dots: twin dots sit on two orbits, trio is three fixed dots (it does not turn)", () => {
  const radii = new Set(dots(AURAS["twin-dots"](input("tool", { units: 4 }))).map(p => Math.round(Math.hypot(...centre(p)))));
  assert.equal(radii.size, 2);
  assert.deepEqual(AURAS.trio(input("tool", { units: 2, t: 0 })), AURAS.trio(input("tool", { units: 2, t: 2.7 })).map(p => p), "trio holds still");
  assert.equal(dots(AURAS.trio(input("tool", { units: 9 }))).length, 3);
});

test("reticle: a ring in four quarters with a gap at each of the four directions, and cross-hairs", () => {
  const out = Rt(input("idle"));
  const quarters = out.filter(p => p.key.startsWith("quarter-"));
  assert.equal(quarters.length, 4);
  for (let k = 0; k < 4; k++) assert.ok(quarters[k].a1 - quarters[k].a0 < Math.PI / 2 - 0.4, "a gap at each direction");
  assert.equal(Rt(input("tool")).filter(p => p.key.startsWith("hair-")).length, 4);
});

test("reticle: a scan line goes round (2.4 s a lap) and every unit leaves a mark where the scan was", () => {
  const scan = t => { const p = byKey(Rt(input("tool", { t, turn: t })), "scan"); return angleOf(...centre(p)); };
  assert.ok(Math.abs(scan(0.6) - 90) < 0.5 && Math.abs(scan(1.2) - 180) < 0.5);
  const out = Rt(input("tool", { units: 2, t: 2, turn: 2, born: [0.6, 1.2], ages: [1.4, 0.8] }));
  const m = out.filter(p => p.key.startsWith("mark-"));
  assert.deepEqual(m.map(p => Math.round(angleOf(p.cx, p.cy))), [90, 180], "where the scan was when each came back");
  assert.ok(m.every(p => p.unit !== undefined && p.tone === 2));
});

test("reticle: marks flash in turn on the check; the quarters stretch into one ring on done; one quarter is missing on error", () => {
  assert.equal(forms(Rt(input("done", { t: 0.4 })))[0], "closed");
  assert.equal(forms(Rt(input("partial", { t: 0.4 })))[0], "gap");
  const err = Rt(input("error", { units: 2, t: 0.8 }));
  assert.equal(err.filter(p => p.key.startsWith("quarter-")).length, 3);
  assert.ok(err.filter(p => p.key.startsWith("quarter-")).every(p => p.tone === "danger"));
  const mid = Rt(input("done", { units: 2, t: 0.16 })).filter(p => p.key.startsWith("quarter-"));
  assert.ok(mid[0].a1 - mid[0].a0 > Math.PI / 2 - 0.5 && mid.length === 4, "stretching");
  assert.equal(units(Rt(input("tool", { units: 99 }))).length, 8);
  assert.ok(deg(1) > 0);
});
