// From the director to the aura: which phase a view is in, what the tracker remembers (when a state began, what the one before it left, when each unit
// came back, whether the turn was checked), the reduced-motion still input, and where the eyes go.
import test from "node:test";
import assert from "node:assert/strict";
import { auraPhaseOf, createTracker, stillInput, STILL_FINISH_SECONDS } from "../src/aura/track.mjs";
import { toolGaze, sweepLook, SWEEP_PERIOD } from "../src/aura/gaze.mjs";
import { AURA_VARIANTS } from "../src/bot-persona.mjs";
import { createDirector } from "../src/bloub-director.mjs";
import { AURAS } from "../src/aura/index.mjs";

const view = (pose, over = {}) => ({ pose, outcome: null, outcomeAge: null, easing: "smooth", tempo: 1, waitingForUser: pose === "hold", ...over });

test("each pose of the director is a phase of the aura", () => {
  const cases = { idle: "idle", reaction: "idle", listen: "listen", attention: "think", waiting: "think", tool: "tool", verify: "verify", answer: "answer", hold: "hold", notify: "unread", sleep: "sleep", offline: "offline" };
  for (const [pose, phase] of Object.entries(cases)) assert.equal(auraPhaseOf(view(pose)), phase, pose);
  assert.equal(auraPhaseOf(view("stinger", { outcome: "done", outcomeAge: 0.1 })), "done");
  assert.equal(auraPhaseOf(view("stinger", { outcome: "error", outcomeAge: 0.1 })), "error");
});

test("a turn that ended keeps its end beat after the director moved on: partial (the nod is 0.6 s), a cancel, an error that outlasts the stinger", () => {
  assert.equal(auraPhaseOf(view("idle", { outcome: "partial", outcomeAge: 0.8 })), "partial");
  assert.equal(auraPhaseOf(view("idle", { outcome: "partial", outcomeAge: 1.2 })), "idle", "a partial beat is 1.12 s");
  assert.equal(auraPhaseOf(view("idle", { outcome: "done", outcomeAge: 1.0 })), "done");
  assert.equal(auraPhaseOf(view("idle", { outcome: "error", outcomeAge: 1.9 })), "error");
  assert.equal(auraPhaseOf(view("idle", { outcome: "error", outcomeAge: 2.1 })), "idle");
  assert.equal(auraPhaseOf(view("idle", { outcome: "cancel", outcomeAge: 0.1 })), "cancel");
  assert.equal(auraPhaseOf(view("idle", { outcome: "cancel", outcomeAge: 0.5 })), "idle");
  assert.equal(auraPhaseOf(view("idle", { outcome: "waiting", outcomeAge: 0.5 })), "idle");
  assert.equal(auraPhaseOf(view("tool", { outcome: "done", outcomeAge: 0.5 })), "tool", "a running turn outranks the last one");
});

test("reduced motion: the closed shape of a finished turn for two seconds (with the check badge), a failure until the next turn", () => {
  assert.equal(STILL_FINISH_SECONDS, 2);
  assert.equal(auraPhaseOf(view("idle", { outcome: "done", outcomeAge: 1.9 }), { still: true }), "done");
  assert.equal(auraPhaseOf(view("idle", { outcome: "done", outcomeAge: 2.1 }), { still: true }), "idle");
  assert.equal(auraPhaseOf(view("idle", { outcome: "partial", outcomeAge: 1 }), { still: true }), "partial");
  assert.equal(auraPhaseOf(view("idle", { outcome: "error", outcomeAge: 600 }), { still: true }), "error");
  assert.equal(auraPhaseOf(view("idle", { outcome: "cancel", outcomeAge: 0.1 }), { still: true }), "idle", "a cancelled turn leaves at once");
  const input = stillInput(view("tool"), 3, true);
  assert.deepEqual([input.phase, input.reduced, input.units, input.verified], ["tool", true, 3, true]);
  // the director in reduced motion: the real chain
  const d = createDirector({ now: 0, reducedMotion: true });
  d.send({ type: "turn-start" }, 1); d.send({ type: "turn-end", outcome: "done" }, 2);
  assert.equal(stillInput(d.read(2.5), 2, false).phase, "done");
  assert.equal(stillInput(d.read(5), 2, false).phase, "idle");
  assert.deepEqual(AURAS.ticks({ ...stillInput(d.read(2.5), 2, false), tier: "L", R: 100 }).map(p => p.form), ["closed"]);
});

test("the tracker: when a state began and what the one before it left", () => {
  const tr = createTracker();
  const a = tr.step({ clock: 10, now: 10, view: view("idle"), units: 0 });
  assert.deepEqual([a.phase, a.t, a.settled], ["idle", 0, null]);
  const b = tr.step({ clock: 10.5, now: 10.5, view: view("waiting"), units: 0 });
  assert.deepEqual([b.phase, b.t], ["think", 0]);
  assert.deepEqual([b.settled.phase, b.settled.units, Math.round(b.settled.t * 100) / 100], ["idle", 0, 0.5]);
  const c = tr.step({ clock: 11.2, now: 11.2, view: view("tool"), units: 0 });
  assert.equal(tr.step({ clock: 11.7, now: 11.7, view: view("tool"), units: 0 }).t, 0.5);
  assert.deepEqual([c.settled.phase, Math.round(c.settled.t * 100) / 100], ["think", 0.7]);
});

test("the tracker: a unit's arrival time, its age and where the turn's own clock was; a result-less call (the units do not move) adds nothing", () => {
  const tr = createTracker();
  tr.step({ clock: 0, now: 100, view: view("waiting"), units: 0 });
  tr.step({ clock: 1, now: 101, view: view("tool"), units: 0 });
  const one = tr.step({ clock: 2, now: 102, view: view("tool"), units: 1 });
  assert.deepEqual([one.units, one.born, one.ages], [1, [2], [0]]);
  const same = tr.step({ clock: 3, now: 103, view: view("tool"), units: 1 });
  assert.deepEqual([same.born, same.ages], [[2], [1]], "an empty result left the units where they were");
  const two = tr.step({ clock: 3.5, now: 103.5, view: view("tool"), units: 2 });
  assert.deepEqual([two.born, two.ages.map(a => Math.round(a * 10) / 10), two.turn], [[2, 3.5], [1.5, 0], 3.5]);
});

test("the tracker: units and the check carry from state to state; a new turn starts clean; the end beat keeps the units it had", () => {
  const tr = createTracker();
  tr.step({ clock: 0, now: 0, view: view("waiting"), units: 0 });
  tr.step({ clock: 1, now: 1, view: view("tool"), units: 2 });
  const v = tr.step({ clock: 2, now: 2, view: view("verify"), units: 2 });
  assert.deepEqual([v.verified, v.units, v.settled.units], [true, 2, 2]);
  const ans = tr.step({ clock: 3, now: 3, view: view("answer"), units: 2 });
  assert.equal(ans.verified, true);
  const done = tr.step({ clock: 4, now: 4, view: view("stinger", { outcome: "done", outcomeAge: 0 }), units: 2 });
  assert.deepEqual([done.phase, done.units, done.t], ["done", 2, 0]);
  // the next message arrives before the beat is over: the units under the closing ring do not change
  const later = tr.step({ clock: 4.2, now: 4.2, view: view("stinger", { outcome: "done", outcomeAge: 0.2 }), units: 0 });
  assert.equal(later.units, 2);
  tr.step({ clock: 9, now: 9, view: view("idle"), units: 0 });
  const fresh = tr.step({ clock: 10, now: 10, view: view("waiting"), units: 0 });
  assert.deepEqual([fresh.verified, fresh.born, fresh.units], [false, [], 0]);
});

test("the tracker: a conversation found waiting for you shows its units without an arrival animation", () => {
  const tr = createTracker();
  const h = tr.step({ clock: 0, now: 0, view: view("hold"), units: 3 });
  assert.deepEqual([h.phase, h.units], ["hold", 3]);
  assert.ok(AURAS.ticks({ ...h, tier: "L", R: 100 }).filter(p => p.unit !== undefined).every(p => p.opacity === 1), "settled, not arriving");
});

test("the tracker's input drives every aura without a problem, for a whole made-up turn", () => {
  for (const variants of Object.values(AURA_VARIANTS)) for (const variant of variants) {
    const tr = createTracker();
    const script = [["idle", 0], ["waiting", 0], ["tool", 0], ["tool", 1], ["tool", 2], ["verify", 2], ["answer", 2], ["stinger", 2]];
    let clock = 0;
    for (const [pose, units] of script) for (let i = 0; i < 12; i++) {
      clock += 0.05;
      const input = tr.step({ clock, now: clock, view: view(pose, pose === "stinger" ? { outcome: "done", outcomeAge: i * 0.05 } : {}), units });
      const prims = AURAS[variant]({ ...input, R: 100, tier: "L" });
      assert.ok(Array.isArray(prims), `${variant} ${pose}`);
    }
  }
});

test("the eyes go where the aura is: left for speed lines, right for page lines, down for the ticker, after the moving point for the rest", () => {
  assert.equal(toolGaze("speed-lines"), "side-left");
  for (const v of ["page-lines", "margin-ticks", "underline"]) assert.equal(toolGaze(v), "side");
  for (const v of ["ticker", "morse", "beacon"]) assert.equal(toolGaze(v), "below");
  for (const v of ["ticks", "gauge", "pips", "halo", "reticle", "orbit-dots", "twin-dots", "trio", "whatever", undefined]) assert.equal(toolGaze(v), "sweep", String(v));
  assert.deepEqual(Object.keys(SWEEP_PERIOD).sort(), ["gauge", "halo", "orbit-dots", "pips", "reticle", "ticks", "trio", "twin-dots"]);
  assert.equal(SWEEP_PERIOD.ticks, 1.6);
  const up = sweepLook(0), right = sweepLook(Math.PI / 2), down = sweepLook(Math.PI), left = sweepLook(1.5 * Math.PI);
  assert.ok(up.pitch > right.pitch && right.pitch > down.pitch);
  assert.ok(right.yaw > 10 && left.yaw < -10 && Math.abs(up.yaw) < 1e-9);
  assert.deepEqual(sweepLook(0.05), sweepLook(0), "a glance in eighths of a turn, not a track");
});
