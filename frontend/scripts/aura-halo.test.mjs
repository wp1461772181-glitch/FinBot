// AppleBot · the breathing halo (design 6.5): a thin ring at 1.3 R; segments per tool, lining up for the check, whole for the output; 1.04 -> 1 on done;
// one segment that never closes on error.  Nothing shakes or overshoots.
import test from "node:test";
import assert from "node:assert/strict";
import { AURAS } from "../src/aura/index.mjs";
import { R, deg, forms, input, units } from "./aura-helpers.mjs";

const H = AURAS.halo;
const segs = prims => prims.filter(p => p.key.startsWith("seg-"));
const gapDeg = prims => { const s = segs(prims); return deg(s[1].a0 - s[0].a1); };

test("at rest: one thin ring at 1.3 R, faint", () => {
  const out = H(input("idle"));
  assert.equal(out.length, 1);
  assert.deepEqual([out[0].kind, out[0].r, out[0].tone], ["arc", 1.3 * R, 0]);
  assert.ok(Math.abs(out[0].a1 - out[0].a0 - 2 * Math.PI) < 1e-3);
  assert.deepEqual(H(input("think")), []);
});

test("tool: a segment per tool call (the one still running too), turning slowly; solid when back, half transparent while running; five at most", () => {
  const out = H(input("tool", { units: 2, t: 1 }));
  assert.equal(segs(out).length, 3, "two back and one running");
  assert.deepEqual(segs(out).map(p => [p.opacity, p.unit !== undefined]), [[1, true], [1, true], [0.5, false]]);
  assert.equal(units(out).length, 2);
  assert.equal(segs(H(input("tool", { units: 9 }))).length, 5);
  const a = segs(H(input("tool", { units: 2, t: 0 })))[0].a0, b = segs(H(input("tool", { units: 2, t: 2.4 })))[0].a0;
  assert.ok(Math.abs(b - a - Math.PI) < 2e-3, "half a lap in 2.4 s: 4.8 s a lap, slow");
  assert.ok(gapDeg(out) > 10, "gaps between the segments");
});

test("check: the segments stop turning and line up, the gaps narrow gradually", () => {
  const out = t => H(input("verify", { units: 3, t, settled: { phase: "tool", units: 3, t: 1.1 } }));
  const first = t => (segs(out(t))[0].a0 + segs(out(t))[0].a1) / 2; // the middle of the first segment
  assert.ok(Math.abs(first(0.6) - first(3)) < 2e-3, "still after the settling");
  const pitch = (2 * Math.PI) / 3, joint = (first(3) - pitch / 2 + pitch) % pitch;
  assert.ok(Math.min(joint, pitch - joint) < 2e-3, "the segments sit on the joints of an even ring");
  assert.ok(gapDeg(out(0)) > gapDeg(out(0.6)) && gapDeg(out(0.6)) > gapDeg(out(1.2)), "narrowing");
  assert.ok(gapDeg(out(1.2)) < 3, "nearly shut");
});
function gapNow(prims) { return segs(prims)[1].a0 - segs(prims)[0].a1; }

test("output: the ring is whole and its brightness breathes every 2.5 s; waiting: whole and still", () => {
  const o = t => segs(H(input("answer", { units: 3, t })))[0].opacity;
  assert.ok(o(0.625) > o(1.875) + 0.2, "bright and dim");
  assert.ok(Math.abs(o(0) - o(2.5)) < 1e-3, "a breath every 2.5 s");
  assert.ok(gapDeg(H(input("answer", { units: 3 }))) < 3, "no gaps to speak of");
  assert.deepEqual(H(input("hold", { units: 3, t: 1 })), H(input("hold", { units: 3, t: 8 })));
});

test("done: the gaps shut and the whole ring settles from 1.04 times to 1 (r 1.352 R to 1.3 R), then it fades", () => {
  const radius = t => H(input("done", { units: 3, t }))[0].r;
  assert.ok(Math.abs(radius(0.001) - 1.3 * R * 1.04) < 0.2);
  assert.ok(radius(0.1) > radius(0.2) && radius(0.2) > radius(0.31), "never below 1: no overshoot");
  const closed = H(input("done", { units: 3, t: 0.5 }));
  assert.deepEqual([closed.length, closed[0].form, closed[0].r], [1, "closed", 1.3 * R]);
  assert.ok(Math.abs(closed[0].a1 - closed[0].a0 - 2 * Math.PI) < 1e-3);
  assert.ok(H(input("done", { units: 3, t: 1.0 }))[0].opacity < 1);
});

test("partial: it closes but for one gap", () => { const p = H(input("partial", { units: 3, t: 0.5 })); assert.deepEqual([p.length, p[0].form], [1, "gap"]); assert.ok(p[0].a1 - p[0].a0 < 2 * Math.PI - 0.2); });

test("error: one segment never closes and the whole ring is darker; it does not move at all", () => {
  const out = H(input("error", { units: 3, t: 0.8 })), later = H(input("error", { units: 3, t: 1.4 }));
  assert.equal(segs(out).length, 2, "one of three is missing");
  assert.ok(segs(out).every(p => p.tone === "danger"));
  assert.ok(segs(out)[0].opacity < 0.7, "darker");
  assert.deepEqual(out.map(p => [p.a0, p.a1]), later.map(p => [p.a0, p.a1]), "not a shake, not a wobble: the same place");
  assert.equal(forms(out)[0], "broken");
});

test("a tracker never overshoots: the spring that TeslaBot uses is not in the halo's own motion (smooth only unless the persona says so)", () => {
  const vals = Array.from({ length: 33 }, (_, i) => H(input("tool", { units: 1, t: i * 0.01, settled: { phase: "idle", units: 0, t: 3 } }))[0].opacity);
  assert.ok(Math.max(...vals) <= 1);
});

test("M: at most four segments", () => { assert.equal(segs(H(input("tool", { tier: "M", units: 9 }))).length, 4); });
