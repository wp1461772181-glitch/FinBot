// The entrance and the exit of every aura (design 6.5, 6.7): each variant defines both phases, they keep to the time limits, they are pure, they
// end where the resting picture begins, and the body poses are continuous.
import test from "node:test";
import assert from "node:assert/strict";
import { AURAS } from "../src/aura/index.mjs";
import { ENTER_LEN, LEAVE_LEN, familyOf, handoffBody } from "../src/aura/handoff.mjs";
import { HANDOFF } from "../src/handoff.mjs";
import { VARIANTS, input } from "./aura-helpers.mjs";

const at = (variant, phase, t, over = {}) => AURAS[variant](input(phase, { t, units: 0, ...over }));

test("the exit lasts at most 160 ms and the entrance at most 400 ms (real time, at any tempo); after that the exit is empty and the entrance is the resting picture", () => {
  assert.ok(LEAVE_LEN <= 0.16 && ENTER_LEN <= 0.4);
  for (const [, variant] of VARIANTS) for (const tempo of [0.8, 1, 1.25]) {
    assert.deepEqual(at(variant, "leave", LEAVE_LEN * tempo + 0.001, { tempo }), [], `${variant} leave is over @${tempo}`);
    assert.notDeepEqual(at(variant, "leave", 0.05 * tempo, { tempo }), [], `${variant} leave is on screen @${tempo}`);
    assert.deepEqual(at(variant, "enter", ENTER_LEN * tempo + 0.001, { tempo }), at(variant, "idle", 5, { settled: null, tempo }), `${variant} enter ends in the resting picture @${tempo}`);
    assert.notDeepEqual(at(variant, "enter", 0.15 * tempo, { tempo }), [], `${variant} enter is on screen @${tempo}`);
  }
});

test("every variant leaves and enters at both tiers with plain data, and under reduced motion there is neither", () => {
  for (const [, variant] of VARIANTS) for (const tier of ["L", "M"]) for (const phase of ["enter", "leave"]) {
    for (const t of [0, 0.03, 0.08, 0.2, 0.39]) {
      const prims = at(variant, phase, t, { tier });
      const keys = new Set();
      for (const p of prims) { assert.ok(!keys.has(p.key), `${variant}/${tier}/${phase}/${t}: key ${p.key}`); keys.add(p.key); assert.ok(p.opacity >= 0 && p.opacity <= 1, `${variant} ${phase} opacity`); }
      assert.ok(prims.length <= 40, `${variant}/${phase}: ${prims.length} nodes`);
      assert.deepEqual(at(variant, phase, t, { tier, reduced: true }), [], `${variant}/${phase} reduced`);
    }
    assert.deepEqual(AURAS[variant](input(phase, { tier: null })), [], "XS / S draw nothing");
    assert.deepEqual(AURAS[variant](input(phase, { tier: "S" })), []);
  }
});

test("the exit and the entrance show no unit and no end form (they are not part of a turn)", () => {
  for (const [, variant] of VARIANTS) for (const phase of ["enter", "leave"]) for (const t of [0.02, 0.1, 0.3]) {
    for (const p of at(variant, phase, t, { units: 5 })) { assert.equal(p.unit, undefined, `${variant}/${phase}`); assert.equal(p.form, undefined, `${variant}/${phase}`); }
  }
});

test("FinBot's ring is drawn from a point to a whole circle on the way in, and draws in to a point on the way out", () => {
  const ring = (phase, t) => at("ticks", phase, t).find(p => p.key === "ring");
  const a = ring("enter", 0.04), b = ring("enter", 0.2);
  assert.ok(a && b && b.a1 > a.a1, "the arc grows");
  assert.ok(Math.abs(ring("enter", 0.28).a1 - 2 * Math.PI) < 0.01, "a whole circle at 70% of the entrance");
  assert.ok(ring("enter", 0.39).opacity < 0.1 && ring("enter", 0.2).opacity === 1, "then the ring goes (the faint ticks are left)");
  const r0 = ring("leave", 0.01).r, r1 = ring("leave", 0.1).r;
  assert.ok(r0 > r1 && r1 < 0.3 * r0, "the ring shrinks toward a point");
  assert.ok(Math.abs(ring("leave", 0.1).a1 - 2 * Math.PI) < 0.001, "it stays a whole circle on the way");
});

test("TeslaBot's lines trail the sliding body: left of it, streaming (dashed), overshooting with the body", () => {
  const flow = (phase, t) => at("speed-lines", phase, t).filter(p => p.key.startsWith("flow-"));
  assert.equal(flow("enter", 0.1).length, 3);
  assert.ok(flow("enter", 0.1).every(p => p.dash && p.x1 < 0 && p.x2 < p.x1), "dashed, trailing to the left");
  const early = flow("enter", 0.05)[1].x1, late = flow("enter", 0.3)[1].x1;
  assert.ok(early < late, "the lines move right with the body");
  const out = flow("leave", 0.1)[1].x1, start = flow("leave", 0.01)[1].x1;
  assert.ok(out > start, "dashing out to the right");
});

test("NewsBot comes in in steps: the picture is shown in quarters, the signal arcs flash lit once, and it is lifted away in steps", () => {
  const opacities = new Set([0.02, 0.1, 0.2, 0.3].map(t => at("ticker", "enter", t).find(p => p.key.startsWith("bar-")).opacity));
  assert.ok(opacities.size >= 2 && [...opacities].every(o => [0.25, 0.5, 0.75, 1].map(v => v * 0.9).some(v => Math.abs(v - o) < 0.01) || o > 0), "stepped, not continuous");
  const lit = t => at("ticker", "enter", t).filter(p => p.key.startsWith("arc-") && p.tone === 2 && p.opacity === 1).length;
  assert.equal(lit(0.1), 2, "both arcs flash at landing");
  assert.equal(lit(0.02) + lit(0.3), 0, "and only then");
  const y = t => at("ticker", "leave", t).find(p => p.key.startsWith("bar-")).y1;
  assert.ok(y(0.1) < y(0.01), "lifted upward");
});

test("AppleBot appears softly from a smaller ring and fades out; ReportBot's page opens and closes about the body's left edge; the generalist's dots gather and scatter", () => {
  const ring = (phase, t) => at("halo", phase, t).find(p => p.key === "ring");
  assert.ok(ring("enter", 0.05).r < ring("enter", 0.35).r && ring("enter", 0.05).opacity < ring("enter", 0.35).opacity);
  assert.ok(ring("leave", 0.1).opacity < ring("leave", 0.01).opacity);
  const right = (phase, t) => Math.max(...at("page-lines", phase, t).map(p => p.x2 ?? p.x ?? -1e9));
  assert.ok(right("enter", 0.05) < right("enter", 0.39), "the page opens");
  assert.ok(right("leave", 0.1) < right("leave", 0.01), "and closes");
  const radius = (variant, phase, t) => { const p = at(variant, phase, t).find(q => q.key === "dot-0"); return Math.hypot(p.cx, p.cy); };
  for (const variant of ["orbit-dots", "twin-dots", "trio"]) {
    assert.ok(radius(variant, "enter", 0.02) > radius(variant, "enter", 0.38), `${variant} gathers`);
    assert.ok(radius(variant, "leave", 0.1) > radius(variant, "leave", 0.01), `${variant} scatters`);
  }
});

test("the body poses: continuous from the exit to the start of the next one to rest; each archetype's own", () => {
  const sample = (from, to) => { const out = []; for (let a = 0; a <= 1.0; a += 0.01) out.push(handoffBody({ from, to, age: a })); return out; };
  for (const [from, to] of [["speed-lines", "page-lines"], ["ticker", "halo"], ["ticks", "speed-lines"], ["orbit-dots", "reticle"]]) {
    const poses = sample(from, to);
    for (let i = 1; i < poses.length; i++) for (const key of Object.keys(poses[i])) assert.ok(Math.abs(poses[i][key] - poses[i - 1][key]) < 0.34, `${from}->${to} ${key} jumps at ${i}`);
    assert.deepEqual(poses[0], { dx: 0, dy: 0, tilt: 0, scale: 1, sx: 1, alpha: 1 });
    assert.deepEqual(handoffBody({ from, to, age: HANDOFF.ENTER_AT + HANDOFF.ENTER }), { dx: 0, dy: 0, tilt: 0, scale: 1, sx: 1, alpha: 1 }, "at rest when the entrance is over");
  }
  assert.ok(handoffBody({ from: "speed-lines", to: "ticks", age: HANDOFF.OUT }).dx > 0.4, "TeslaBot leaves to the right");
  assert.ok(handoffBody({ from: "ticks", to: "speed-lines", age: HANDOFF.ENTER_AT }).dx < -0.4, "TeslaBot arrives from the left");
  assert.ok(handoffBody({ from: "ticker", to: "ticks", age: HANDOFF.OUT }).dy < -0.4, "NewsBot leaves upward");
  assert.ok(handoffBody({ from: "ticks", to: "ticker", age: HANDOFF.ENTER_AT }).dy < -0.5, "NewsBot arrives from above");
  const drop = a => handoffBody({ from: "ticks", to: "ticker", age: HANDOFF.ENTER_AT + a * HANDOFF.ENTER }).dy;
  assert.ok(drop(0.3) > -0.01 && drop(0.55) < drop(0.3) && drop(0.9) > drop(0.55), "two steps: it lands, bounces up, lands again");
  assert.ok(handoffBody({ from: "page-lines", to: "ticks", age: HANDOFF.OUT }).sx < 0.5, "ReportBot's page turns out");
  assert.ok(handoffBody({ from: "ticks", to: "halo", age: HANDOFF.ENTER_AT }).scale < 0.95 && handoffBody({ from: "ticks", to: "halo", age: HANDOFF.ENTER_AT }).alpha < 0.6, "AppleBot starts at about 0.92 and half transparent");
  const overshoot = Math.max(...sample("ticks", "speed-lines").map(p => p.dx));
  assert.ok(overshoot > 0.01 && overshoot < 0.1, `TeslaBot overshoots a little (${overshoot})`);
  assert.equal(familyOf("beacon"), "ticker"); assert.equal(familyOf("unheard-of"), "dots");
});
