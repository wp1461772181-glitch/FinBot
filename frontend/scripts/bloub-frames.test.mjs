import test from "node:test";
import assert from "node:assert/strict";
import { SETTLE, frameDemand, needsFrames } from "../src/bloub-frames.mjs";
import { ENGAGE_TIME } from "../src/bloub-gaze.mjs";
import { MOOD_MORPH } from "../src/bloub-mood.mjs";

test("a settled idle avatar that nobody hovers needs no frames", () => {
  assert.equal(needsFrames({ state: "idle" }), false);
  assert.equal(needsFrames({ state: "idle", hovered: false, aiming: false, quietFor: Infinity }), false);
  assert.equal(needsFrames({ state: "idle", quietFor: SETTLE + 0.01 }), false);
});

test("a hovered row (the eyes follow the pointer) needs frames, however long it has been quiet", () => {
  assert.equal(needsFrames({ state: "idle", hovered: true }), true);
  assert.equal(needsFrames({ state: "idle", hovered: true, quietFor: 100 }), true);
});

test("orbit (answering) and notify (unread) always run", () => {
  for (const state of ["orbit", "notify"]) {
    assert.equal(needsFrames({ state }), true, state);
    assert.equal(needsFrames({ state, quietFor: 100 }), true, state);
    assert.equal(frameDemand({ state }), true, state);
  }
});

test("going back to idle keeps the loop until the engine's transitions are over, then stops", () => {
  assert.equal(needsFrames({ state: "idle", quietFor: 0 }), true);
  assert.equal(needsFrames({ state: "idle", quietFor: SETTLE - 0.01 }), true);
  assert.equal(needsFrames({ state: "idle", quietFor: SETTLE }), false);
});

test("a hover that ended is not over until the gaze has eased back", () => {
  assert.equal(needsFrames({ state: "idle", hovered: false, aiming: true }), true);   // eyes still aimed at where the pointer was
  assert.equal(needsFrames({ state: "idle", quietFor: 0.3 }), true);                  // release morph just started
  assert.equal(needsFrames({ state: "idle", quietFor: ENGAGE_TIME + 0.05 }), true); 
  assert.equal(needsFrames({ state: "idle", quietFor: SETTLE + 0.01 }), false);
});

test("SETTLE covers the gaze release, the work face fade and the longest state morph, with a margin", () => {
  assert.ok(SETTLE >= ENGAGE_TIME + 0.05, "gaze release");
  assert.ok(SETTLE >= MOOD_MORPH + 0.05, "work face fade");
  assert.ok(SETTLE >= 0.6 + 0.05, "longest engine state morph (orbit)");
  assert.ok(SETTLE < 3, "stays short: the point is to stop");
});

test("frameDemand ignores the quiet timer", () => {
  assert.equal(frameDemand({ state: "idle", quietFor: 0 }), false);
  assert.equal(frameDemand({ state: "idle", hovered: true }), true);
  assert.equal(frameDemand({ state: "idle", aiming: true }), true);
});
