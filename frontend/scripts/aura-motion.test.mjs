// The body's small movements that go with an aura (design 6.5): TeslaBot's dart, brake and lean-back, AppleBot's settle.
import test from "node:test";
import assert from "node:assert/strict";
import { bodyMotion, dart, REST } from "../src/aura/motion.mjs";

test("TeslaBot darts right 0.12 R and back: out in 160 ms, back in 240 ms", () => {
  assert.equal(dart(0), 0); assert.ok(Math.abs(dart(0.16) - 1) < 1e-9); assert.equal(dart(0.4), 0); assert.equal(dart(2), 0);
  assert.ok(dart(0.08) > 0 && dart(0.08) < 1 && dart(0.28) > 0 && dart(0.28) < 1);
  const out = real => bodyMotion({ variant: "speed-lines", phase: "tool", real }).dx;
  assert.ok(Math.abs(out(0.16) - 0.12) < 1e-9);
  assert.ok(out(0.05) < out(0.16) && out(0.3) < out(0.16) && out(0.4) === 0);
  // each unit that comes back darts again
  assert.ok(Math.abs(bodyMotion({ variant: "speed-lines", phase: "tool", real: 3, ages: [3, 0.16] }).dx - 0.12) < 1e-9);
  assert.equal(bodyMotion({ variant: "speed-lines", phase: "tool", real: 3, ages: [3, 2.5] }).dx, 0);
});

test("TeslaBot brakes on done (past upright by 2 degrees, then settled) and leans back 6 degrees on error", () => {
  const brake = real => bodyMotion({ variant: "speed-lines", phase: "done", real }).tilt;
  assert.equal(brake(0), 0); assert.ok(Math.abs(brake(0.25) + 2) < 1e-9, "-2 degrees at the deepest"); assert.ok(Math.abs(brake(0.5)) < 1e-9); assert.ok(Math.abs(brake(1.2)) < 1e-9);
  const back = real => bodyMotion({ variant: "speed-lines", phase: "error", real }).tilt;
  assert.equal(back(0), 0); assert.equal(back(0.2), -6); assert.equal(back(1.5), -6);
  assert.equal(bodyMotion({ variant: "speed-lines", phase: "error", reduced: true }).tilt, -6, "a posture, so the still frame has it");
  assert.deepEqual(bodyMotion({ variant: "speed-lines", phase: "tool", reduced: true, real: 0.1 }), REST);
});

test("AppleBot settles from 1.04 times its size to 1 on done and partial, never below 1", () => {
  const s = real => bodyMotion({ variant: "halo", phase: "done", real }).scale;
  assert.equal(s(0), 1.04); assert.ok(s(0.1) < 1.04 && s(0.1) > s(0.2) && s(0.2) > 1); assert.equal(s(0.32), 1); assert.equal(s(2), 1);
  assert.ok(bodyMotion({ variant: "halo", phase: "partial", real: 0 }).scale > 1);
  assert.deepEqual(bodyMotion({ variant: "halo", phase: "done", reduced: true }), REST);
  assert.deepEqual(bodyMotion({ variant: "halo", phase: "error", real: 0.5 }), REST, "no shaking on failure");
});

test("every other bot's body does nothing extra", () => {
  for (const variant of ["ticks", "ticker", "page-lines", "orbit-dots", "reticle", undefined]) for (const phase of ["tool", "done", "error", "partial"]) assert.deepEqual(bodyMotion({ variant, phase, real: 0.1 }), REST, `${variant}/${phase}`);
});
