// The contract every aura keeps (design 6.2, 6.9): every variant of bot-persona has an aura, every state is defined, primitives are plain data in
// the allowed tones, the function is pure, reduced motion is static, M is smaller than L, XS / S have nothing.
import test from "node:test";
import assert from "node:assert/strict";
import { AURA_VARIANTS } from "../src/bot-persona.mjs";
import { AURAS, auraFor } from "../src/aura/index.mjs";
import { TONES, endLength } from "../src/aura/shared.mjs";
import { PHASES, VARIANTS, input, units } from "./aura-helpers.mjs";

const KINDS = ["line", "arc", "dot", "rect", "path"];
const FORMS = ["closed", "gap", "broken"];
const finite = p => Object.entries(p).every(([k, v]) => typeof v !== "number" || Number.isFinite(v));

test("every aura variant a persona can have is drawn (the variant -> function table is complete, one function per name)", () => {
  assert.equal(VARIANTS.length, 15);
  for (const [, variant] of VARIANTS) assert.equal(typeof AURAS[variant], "function", variant);
  assert.deepEqual(Object.keys(AURAS).sort(), Object.values(AURA_VARIANTS).flat().sort(), "no aura without a persona variant, no variant without an aura");
  assert.equal(auraFor("no-such-variant"), AURAS["orbit-dots"], "a bad name falls back to the generalist's: a bot always has a complete aura");
});

test("every state of every aura is defined, as plain data: kinds, finite numbers, unique keys, allowed tones and forms, opacity 0..1", () => {
  for (const [, variant] of VARIANTS) for (const tier of ["L", "M"]) for (const phase of PHASES) for (const t of [0, 0.2, 0.9, 3.7]) for (const n of [0, 1, 3, 8, 40]) {
    const prims = AURAS[variant](input(phase, { t, units: n, tier }));
    const where = `${variant}/${tier}/${phase}/t${t}/n${n}`;
    assert.ok(Array.isArray(prims), where);
    const keys = new Set();
    for (const p of prims) {
      assert.ok(KINDS.includes(p.kind), `${where}: kind ${p.kind}`);
      assert.ok(TONES.includes(p.tone), `${where}: tone ${p.tone}`);
      assert.ok(p.opacity >= 0 && p.opacity <= 1, `${where}: opacity ${p.opacity}`);
      assert.ok(finite(p), `${where}: ${JSON.stringify(p)}`);
      assert.ok(typeof p.key === "string" && p.key && !keys.has(p.key), `${where}: key ${p.key}`);
      keys.add(p.key);
      if (p.form) assert.ok(FORMS.includes(p.form), where);
      if (p.kind === "arc") assert.ok(p.a1 >= p.a0, `${where}: arc runs clockwise`);
    }
  }
});

test("pure: the same input gives the same output, the input is not touched, nothing reads a clock, a global or a random number", () => {
  const realRandom = Math.random, realNow = Date.now;
  Math.random = () => { throw new Error("random"); }; Date.now = () => { throw new Error("clock"); };
  try {
    for (const [, variant] of VARIANTS) for (const phase of PHASES) {
      const frozen = Object.freeze({ ...input(phase, { t: 1.3, units: 4, ages: Object.freeze([9, 9, 0.1, 0.05]), born: Object.freeze([0, 1, 2, 3]), settled: Object.freeze({ phase: "idle", units: 0, t: 2 }) }) });
      assert.deepEqual(AURAS[variant](frozen), AURAS[variant]({ ...frozen }), `${variant}/${phase}`);
    }
  } finally { Math.random = realRandom; Date.now = realNow; }
});

test("units that have not changed do not change the picture: the same units at the same time, however they got there", () => {
  for (const [, variant] of VARIANTS) {
    const a = AURAS[variant](input("verify", { units: 3, t: 0.7 })), b = AURAS[variant](input("verify", { units: 3, t: 0.7, ages: [Infinity, Infinity, Infinity] }));
    assert.deepEqual(a, b, variant);
  }
});

test("reduced motion: a static shape that does not depend on time, units still count, a finished turn is its finished shape", () => {
  for (const [, variant] of VARIANTS) for (const phase of PHASES) {
    const at = t => AURAS[variant](input(phase, { reduced: true, t, units: 3, ages: [0, 0, 0], verified: true }));
    assert.deepEqual(at(0), at(0.7), `${variant}/${phase}`);
    assert.deepEqual(at(0), at(33), `${variant}/${phase}`);
  }
  for (const [, variant] of VARIANTS) {
    const done = AURAS[variant](input("done", { reduced: true })), error = AURAS[variant](input("error", { reduced: true }));
    assert.equal(done.filter(p => p.form === "closed").length, 1, `${variant}: done is the closed shape`);
    assert.ok(error.some(p => p.form === "broken"), `${variant}: error is the broken shape`);
    assert.equal(AURAS[variant](input("partial", { reduced: true })).filter(p => p.form === "gap").length, 1, `${variant}: partial closes but one gap`);
    assert.equal(units(AURAS[variant](input("tool", { reduced: true, units: 2 }))).length, variant === "trio" ? 2 : 2, `${variant}: units show at once`);
  }
});

test("the end beats: closed (done), gap (partial), broken (error) appear at the end of the close, and nothing is left after the beat is over", () => {
  for (const [, variant] of VARIANTS) {
    const closeEnd = 0.45; // past the 0.32 close of done / partial and the 0.4 break of error
    assert.equal(AURAS[variant](input("done", { t: closeEnd })).filter(p => p.form === "closed").length, 1, `${variant} done`);
    assert.equal(AURAS[variant](input("partial", { t: closeEnd })).filter(p => p.form === "gap").length, 1, `${variant} partial`);
    assert.ok(AURAS[variant](input("error", { t: 0.8 })).some(p => p.form === "broken"), `${variant} error`);
    for (const phase of ["done", "partial", "error"]) assert.deepEqual(AURAS[variant](input(phase, { t: endLength(phase) + 0.01 })), [], `${variant} ${phase} is gone at the end`);
    assert.ok(AURAS[variant](input("error", { t: 1.5 })).every(p => p.opacity > 0.5 || p.tone === 0 || p.tone === "danger"), `${variant}: the red holds`);
    // a closed shape fades only in the last part
    const closed = AURAS[variant](input("done", { t: 0.7 })).find(p => p.form === "closed"), fading = AURAS[variant](input("done", { t: 1.05 })).find(p => p.form === "closed");
    assert.equal(closed.opacity, 1, variant); assert.ok(fading.opacity < 1, variant);
  }
});

test("the end beats keep the skeleton at any tempo: done <= 1.4 s, failed <= 2.0 s in real time", () => {
  for (const [, variant] of VARIANTS) for (const tempo of [0.8, 1, 1.25]) {
    assert.deepEqual(AURAS[variant](input("done", { t: 1.4 * tempo, tempo })), [], `${variant} done @${tempo}`);
    assert.deepEqual(AURAS[variant](input("error", { t: 2.0 * tempo, tempo })), [], `${variant} error @${tempo}`);
    assert.notDeepEqual(AURAS[variant](input("error", { t: 1.9 * tempo, tempo })), [], `${variant} error still there at 1.9 s @${tempo}`);
  }
});

test("a state is entered within 320 ms: by then the picture is the state's own, whatever came before", () => {
  for (const [, variant] of VARIANTS) {
    const settled = { phase: "idle", units: 0, t: 3 };
    const later = AURAS[variant](input("tool", { t: 0.32, tempo: 1, settled })), steady = AURAS[variant](input("tool", { t: 0.32 }));
    assert.deepEqual(later, steady, variant);
  }
});

test("size: XS and S draw nothing, M is smaller than L (fewer units, fewer nodes), L stays within about 40 nodes", () => {
  for (const [, variant] of VARIANTS) {
    let most = 0;
    for (const phase of PHASES) for (const t of [0.1, 0.5, 1.1]) {
      const l = AURAS[variant](input(phase, { t, units: 12 })), m = AURAS[variant](input(phase, { t, units: 12, tier: "M" }));
      assert.ok(units(m).length <= units(l).length, `${variant}/${phase}: M units`);
      assert.ok(m.length <= l.length + 1, `${variant}/${phase}: M is not bigger`);
      most = Math.max(most, l.length);
    }
    assert.ok(most <= 40, `${variant}: ${most} nodes`);
    assert.ok(units(AURAS[variant](input("tool", { units: 12, tier: "M" }))).length <= 5, `${variant}: M shows at most five units`);
  }
});

test("units are capped per aura (4 to 12) and a unit count of 0 shows no unit", () => {
  const caps = { ticks: 12, gauge: 10, pips: 12, "speed-lines": 5, halo: 5, reticle: 8, ticker: 5, morse: 5, beacon: 5, "page-lines": 12, "margin-ticks": 12, underline: 12, "orbit-dots": 6, "twin-dots": 6, trio: 3 };
  for (const [, variant] of VARIANTS) {
    assert.equal(units(AURAS[variant](input("tool", { units: 99 }))).length, variant.includes("lines") && variant.startsWith("page") || variant === "margin-ticks" || variant === "underline" ? 4 : caps[variant], `${variant} cap`);
    assert.equal(units(AURAS[variant](input("tool", { units: 0 }))).length, 0, `${variant} no units`);
    assert.ok(caps[variant] >= 3 && caps[variant] <= 12);
  }
});

test("only the working and ending states show units; resting, listening, thinking, cancelled, unread, asleep and offline show none", () => {
  for (const [, variant] of VARIANTS) for (const phase of ["idle", "listen", "think", "cancel", "unread", "sleep", "offline"]) {
    assert.equal(units(AURAS[variant](input(phase, { units: 4 }))).length, 0, `${variant}/${phase}`);
  }
});
