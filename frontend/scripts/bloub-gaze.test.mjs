import test from "node:test";
import assert from "node:assert/strict";
import { YAW_MAX, PITCH, PITCH_MAX, TOUR_TIME, aimFromPointer, followLook, tourLook, pointerFresh, POINTER_STALE } from "../src/bloub-gaze.mjs";

const box = { left: 90, top: 10, width: 30, height: 30 };
const view = { width: 1000, height: 800 };

test("pointer right of the bot turns the head right, left turns it left, bounded by YAW_MAX", () => {
  const right = followLook(aimFromPointer({ x: 900, y: 25 }, box, view));
  const left = followLook(aimFromPointer({ x: 5, y: 25 }, box, view));
  assert.ok(right.yaw > 0 && left.yaw < 0);
  assert.ok(Math.abs(right.yaw) <= YAW_MAX && Math.abs(left.yaw) <= YAW_MAX);
  const far = followLook(aimFromPointer({ x: 1e9, y: -1e9 }, box, view));
  assert.equal(far.yaw, YAW_MAX);
  assert.equal(far.pitch, PITCH + PITCH_MAX); // above the bot = look up
});

test("pointer below the bot looks down (screen y grows downwards, pitch grows upwards)", () => {
  assert.ok(followLook(aimFromPointer({ x: 105, y: 700 }, box, view)).pitch < PITCH);
  assert.ok(followLook(aimFromPointer({ x: 105, y: 0 }, box, view)).pitch > PITCH - 1e-9);
});

test("a zero-size box or non-finite input gives no aim instead of NaN", () => {
  assert.equal(aimFromPointer({ x: 1, y: 1 }, { left: 0, top: 0, width: 0, height: 0 }, view), null);
  assert.equal(aimFromPointer({ x: NaN, y: 1 }, box, view), null);
  assert.equal(aimFromPointer(null, box, view), null);
  assert.equal(aimFromPointer({ x: 1, y: 1 }, box, { width: 0, height: 0 }) !== null, true); // viewport floor of 1px, not 0/0
});

test("engaged gaze takes over the pose and silences the drift; the ramp starts at 0", () => {
  const aim = aimFromPointer({ x: 500, y: 400 }, box, view);
  const a = followLook(aim, 0), b = followLook(aim, 1);
  assert.deepEqual([a.mix, b.mix, b.wander, b.spin], [0, 1, 0, 0]);
});

test("pointer staleness: still or gone pointer releases the gaze", () => {
  assert.equal(pointerFresh(10, 10 + POINTER_STALE - 0.1), true);
  assert.equal(pointerFresh(10, 10 + POINTER_STALE + 0.1), false);
  assert.equal(pointerFresh(null, 10), false);
});

test("arrival gaze: eyes travel a full turn and land with mix 0", () => {
  assert.equal(tourLook(0).spin, 360);
  assert.equal(tourLook(TOUR_TIME).spin, 0);
  assert.equal(tourLook(TOUR_TIME * 2).spin, 0);
  for (const t of [0, 0.4, 1, TOUR_TIME]) assert.equal(tourLook(t).mix, 0);
  assert.ok(tourLook(0.6).spin < 360 && tourLook(0.6).spin > 0);
});

// A1: resting gaze presets.
import { GLANCE_PERIOD, LOOK_BELOW, LOOK_FRONT, SCAN_PERIOD, restLook, restTilt } from "../src/bloub-gaze.mjs";

test("rest gaze: follow (and anything unknown) leaves it to the pointer; the other kinds are absolute looks inside the head limits", () => {
  assert.equal(restLook("follow", 3), null);
  assert.equal(restLook("nonsense", 3), null);
  assert.equal(restLook(undefined), null);
  for (const kind of ["ahead-right", "scan", "down", "front", "side", "below"]) {
    for (const t of [0, 1, 3.5, 4.5, 5.5, 7, 100]) {
      const look = restLook(kind, t);
      assert.ok(look && look.mix === 1 && look.spin === 0, `${kind}@${t}`);
      assert.ok(Math.abs(look.yaw) <= YAW_MAX && Math.abs(look.pitch) <= PITCH_MAX, `${kind}@${t} within limits`);
    }
  }
});

test("rest gaze: the five bots look in five different directions", () => {
  const ahead = restLook("ahead-right", 0), front = restLook("front", 0), down = restLook("down", 0), scanStart = restLook("scan", 0);
  assert.ok(ahead.yaw > 5, "TeslaBot: ahead and to the right");
  assert.equal(front.yaw, 0); assert.equal(front.pitch, PITCH);
  assert.ok(down.pitch < PITCH - 10, "ReportBot: down, reading");
  assert.deepEqual(scanStart, LOOK_FRONT);
  assert.notDeepEqual([ahead.yaw, ahead.pitch], [front.yaw, front.pitch]);
  assert.notDeepEqual([down.yaw, down.pitch], [front.yaw, front.pitch]);
  assert.ok(restLook("side", 0).yaw > 8, "a tool runs: look to the aura's side");
  assert.deepEqual(restLook("below", 9), LOOK_BELOW);
});

test("rest gaze: scan sweeps left then right every ~5 s and rests on the front in between; down glances up once per 6 s", () => {
  assert.equal(SCAN_PERIOD, 5); assert.equal(GLANCE_PERIOD, 6);
  for (const base of [0, SCAN_PERIOD, SCAN_PERIOD * 7]) {
    assert.deepEqual(restLook("scan", base + 1), LOOK_FRONT);
    assert.ok(restLook("scan", base + 3.5).yaw < -5, "left first");
    assert.ok(restLook("scan", base + 4.5).yaw > 5, "then right");
    assert.deepEqual(restLook("scan", base + 4.95), LOOK_FRONT);
  }
  for (const base of [0, GLANCE_PERIOD, GLANCE_PERIOD * 3]) {
    assert.deepEqual(restLook("down", base + 2), LOOK_BELOW);
    assert.deepEqual(restLook("down", base + 5.4), LOOK_FRONT, "looks up at you");
    assert.deepEqual(restLook("down", base + 5.9), LOOK_BELOW);
  }
  assert.deepEqual(restLook("scan", -3), restLook("scan", 0));
  assert.deepEqual(restLook("scan", NaN), restLook("scan", 0));
});

test("rest gaze: only the tracker's forward look leans the body (6 degrees)", () => {
  assert.equal(restTilt("ahead-right"), 6);
  for (const kind of ["follow", "scan", "down", "front", "side", "below", undefined]) assert.equal(restTilt(kind), 0);
});
