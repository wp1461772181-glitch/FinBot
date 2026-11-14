import assert from "node:assert/strict";
import test from "node:test";
import { HANDOFF, handoffDirection, movesFocus, sourceOfClick } from "../src/handoff.mjs";
import { isRapid, lineMotion, playsSwirl, staggerDelay } from "../src/handoff-line.mjs";

test("the timeline keeps to design 6.7: leave <= 160 ms, enter <= 400 ms, content (focus) by 300 ms, the swirl gone by 1.3 s", () => {
  assert.ok(HANDOFF.OUT <= 0.16 && HANDOFF.SWAP <= 0.16);
  assert.ok(HANDOFF.ENTER <= 0.4 && HANDOFF.ENTER_AT + HANDOFF.ENTER <= HANDOFF.SWIRL_END);
  assert.ok(HANDOFF.FOCUS_BY <= 0.3 && HANDOFF.SWIRL_END <= 1.3);
  assert.ok(HANDOFF.SWAP + HANDOFF.COLOR <= HANDOFF.ENTER_AT, "the colour has arrived before the entrance starts");
});

test("a phone's line slides toward the target's side of the list: +1 further down, -1 further up, 0 when unknown or the same", () => {
  const order = ["a", "b", "c", "d"];
  assert.equal(handoffDirection(order, "a", "c"), 1);
  assert.equal(handoffDirection(order, "d", "b"), -1);
  assert.equal(handoffDirection(order, "b", "b"), 0);
  assert.equal(handoffDirection(order, "a", "zzz"), 0);
  assert.equal(handoffDirection(order, null, "a"), 0);
  assert.equal(handoffDirection(undefined, "a", "b"), 0);
});

test("focus rule: a pointer click or a drawer choice moves the focus to the composer; the keyboard and the address do not", () => {
  assert.equal(sourceOfClick(1), "pointer");
  assert.equal(sourceOfClick(2), "pointer");
  assert.equal(sourceOfClick(0), "keyboard");
  assert.equal(sourceOfClick(0, true), "drawer");
  assert.equal(sourceOfClick(1, true), "drawer");
  assert.deepEqual(["pointer", "drawer", "keyboard", "route", undefined].map(movesFocus), [true, true, false, false, false]);
});

test("only the last three messages fade in, 20 ms apart from 160 ms; earlier ones are shown at once", () => {
  const delays = [0, 1, 2, 3, 4].map(i => staggerDelay(i, 5));
  assert.deepEqual(delays.slice(0, 2), [null, null]);
  assert.deepEqual(delays.slice(2).map(d => Math.round(d * 1000)), [160, 180, 200]);
  assert.deepEqual([0, 1].map(i => Math.round(staggerDelay(i, 2) * 1000)), [160, 180], "a short line animates all it has");
  assert.equal(staggerDelay(0, 0), null);
  assert.equal(staggerDelay(7, 5), null);
  assert.equal(staggerDelay(4, 5, { reduced: true }), null, "reduced motion: nothing staggers");
});

test("a second switch within 300 ms is one gesture with the first", () => {
  assert.equal(isRapid(1, 1.2), true);
  assert.equal(isRapid(1, 1.31), false);
  assert.equal(isRapid(null, 5), false);
  assert.equal(isRapid(undefined, 5), false);
});

test("the line moves by level: crossfade when reduced or off, slide on a phone, rise elsewhere; swirl only at full", () => {
  assert.equal(lineMotion({ reduced: true, phone: true }), "crossfade");
  assert.equal(lineMotion({ level: "off" }), "crossfade");
  assert.equal(lineMotion({ phone: true }), "slide");
  assert.equal(lineMotion({ level: "lite", phone: true }), "slide", "lite keeps the line's transition");
  assert.equal(lineMotion({}), "rise");
  assert.deepEqual([{}, { level: "lite" }, { level: "off" }, { reduced: true }].map(playsSwirl), [true, false, false, false]);
});
