import assert from "node:assert/strict";
import test from "node:test";
import {
  LOW_CORES, LOW_MEMORY_GB, isLowEnd, readHardware, resolveMotionLevel
} from "../src/motion-resolve.mjs";
import { LEVELS, MOTION_KEY, storedMotionLevel } from "../src/motion-level.mjs";
import { saveMotionLevel } from "../src/motion-control.mjs";
import { GAP_MS, SLOW_FRAME_MS, WATCH_WINDOW_MS, createFrameWatch } from "../src/motion-watch.mjs";

const memoryStorage = () => { const map = new Map(); return { getItem: k => map.has(k) ? map.get(k) : null, setItem: (k, v) => void map.set(k, String(v)), removeItem: k => void map.delete(k), map }; };
const LOW = { cores: 4, memoryGB: 4, saveData: false };
const BIG = { cores: 8, memoryGB: 16, saveData: false };

test("thresholds are named: 4 cores and 4 GB (both), or data-saver", () => {
  assert.equal(LOW_CORES, 4);
  assert.equal(LOW_MEMORY_GB, 4);
  assert.deepEqual(LEVELS, ["full", "lite", "off"]);
  assert.equal(isLowEnd({ cores: 4, memoryGB: 4 }), true, "both at the limit counts as low");
  assert.equal(isLowEnd({ cores: 2, memoryGB: 2 }), true);
  assert.equal(isLowEnd({ cores: 5, memoryGB: 4 }), false, "5 cores is over");
  assert.equal(isLowEnd({ cores: 4, memoryGB: 8 }), false, "4 cores with 8 GB is a plain laptop");
  assert.equal(isLowEnd({ cores: 4 }), false, "memory not reported (Safari / Firefox): not low");
  assert.equal(isLowEnd({ memoryGB: 2 }), false, "cores not reported: not low");
  assert.equal(isLowEnd({ cores: 16, memoryGB: 32, saveData: true }), true, "data-saver alone is enough");
  assert.equal(isLowEnd({ cores: 16, memoryGB: 32, saveData: false }), false);
  assert.equal(isLowEnd(undefined), false);
  assert.equal(isLowEnd({ cores: 0, memoryGB: 0 }), false, "zero is 'unknown', not a tiny device");
});

test("priority: system > the reader's choice > device > runtime > default", () => {
  assert.deepEqual(resolveMotionLevel({}), { level: "full", source: "default" });
  assert.deepEqual(resolveMotionLevel({ hardware: BIG }), { level: "full", source: "default" });
  assert.deepEqual(resolveMotionLevel({ hardware: LOW }), { level: "lite", source: "auto-device" });
  assert.deepEqual(resolveMotionLevel({ hardware: BIG, runtimeDowngraded: true }), { level: "lite", source: "auto-runtime" });
  assert.deepEqual(resolveMotionLevel({ stored: "full", hardware: LOW }), { level: "full", source: "user" }, "a hand-picked level beats the device judgement");
  assert.deepEqual(resolveMotionLevel({ stored: "off", hardware: BIG }), { level: "off", source: "user" });
  assert.deepEqual(resolveMotionLevel({ stored: "lite" }), { level: "lite", source: "user" });
  assert.deepEqual(resolveMotionLevel({ prefersReduced: true, stored: "full", hardware: LOW }), { level: "off", source: "system" });
});

test("the system's reduced motion cannot be got round by a setting", () => {
  for (const stored of [undefined, null, "full", "lite", "off", "bogus"]) {
    for (const hardware of [undefined, LOW, BIG]) {
      for (const runtimeDowngraded of [false, true]) {
        assert.deepEqual(resolveMotionLevel({ stored, prefersReduced: true, hardware, runtimeDowngraded }), { level: "off", source: "system" });
      }
    }
  }
});

test("hardware is read from the navigator, and a missing one is just unknown", () => {
  assert.deepEqual(readHardware({ hardwareConcurrency: 4, deviceMemory: 2, connection: { saveData: true } }), { cores: 4, memoryGB: 2, saveData: true });
  assert.deepEqual(readHardware({ hardwareConcurrency: 8 }), { cores: 8, memoryGB: undefined, saveData: undefined });
  assert.equal(isLowEnd(readHardware({ hardwareConcurrency: 8 })), false);
  assert.equal(isLowEnd(readHardware(undefined)), false);
});

test("a runtime drop only touches what nothing above decided", () => {
  assert.equal(resolveMotionLevel({ stored: "full", runtimeDowngraded: true }).level, "full", "hand-picked 'full' stays");
  assert.equal(resolveMotionLevel({ stored: "off", runtimeDowngraded: true }).level, "off");
  assert.equal(resolveMotionLevel({ stored: "lite", runtimeDowngraded: true }).source, "user");
  assert.deepEqual(resolveMotionLevel({ hardware: LOW, runtimeDowngraded: true }), { level: "lite", source: "auto-device" }, "already lite: the source stays the device");
  assert.deepEqual(resolveMotionLevel({ runtimeDowngraded: false }), { level: "full", source: "default" });
});

test("the stored choice: bad values are ignored, only valid ones are written, null forgets", () => {
  const storage = memoryStorage();
  assert.equal(storedMotionLevel(storage), null);
  storage.map.set(MOTION_KEY, "turbo");
  assert.equal(storedMotionLevel(storage), null, "a bad value is ignored");
  assert.equal(resolveMotionLevel({ stored: storedMotionLevel(storage), hardware: BIG }).source, "default");
  assert.equal(saveMotionLevel("lite", storage), "lite");
  assert.equal(storage.map.get(MOTION_KEY), "lite");
  assert.equal(saveMotionLevel("turbo", storage), "lite", "an invalid level changes nothing");
  assert.equal(saveMotionLevel(null, storage), null);
  assert.equal(storage.map.has(MOTION_KEY), false);
  assert.equal(storedMotionLevel({ getItem() { throw new Error("blocked"); } }), null, "storage that throws is no storage");
  assert.ok(MOTION_KEY.includes(":v1"), "the key carries a version");
});

// --- the frame watch ------------------------------------------------------------------------------------------------------------

const feed = (watch, ms, count) => { let last = false; for (let i = 0; i < count; i++) last = watch.step(ms); return last; };

test("watch: constants are the agreed ones", () => {
  assert.equal(SLOW_FRAME_MS, 24);
  assert.equal(WATCH_WINDOW_MS, 2000);
  assert.equal(GAP_MS, 250);
});

test("watch: a steady 60 fps never triggers", () => {
  const watch = createFrameWatch();
  assert.equal(feed(watch, 16.7, 600), false);
});

test("watch: average over 24 ms for a full 2 seconds triggers; at 24 ms exactly it does not", () => {
  assert.equal(feed(createFrameWatch(), 24, 400), false, "24 ms is not MORE than 24 ms");
  const watch = createFrameWatch();
  assert.equal(feed(watch, 25, 79), false, "79 frames = 1975 ms: the window is not full yet");
  assert.equal(watch.step(25), true, "the 80th frame completes 2000 ms at 25 ms each");
  assert.equal(feed(createFrameWatch(), 100, 19), false, "1900 ms of 100 ms frames: still short of 2 s");
  assert.equal(feed(createFrameWatch(), 100, 20), true);
});

test("watch: the window slides (a slow patch straddling a boundary is still seen)", () => {
  const watch = createFrameWatch();
  feed(watch, 16, 100); // 1.6 s fine
  assert.equal(feed(watch, 40, 40), true, "then 1.6 s of 40 ms frames: the last 2 s average > 24");
  const calm = createFrameWatch();
  feed(calm, 40, 25); // 1 s slow
  assert.equal(feed(calm, 16, 200), false, "recovered: the slow second slid out");
});

test("watch: one long frame is not a pattern", () => {
  const watch = createFrameWatch();
  feed(watch, 16.7, 60);
  assert.equal(watch.step(200), false);
  assert.equal(feed(watch, 16.7, 120), false);
});

test("watch: an interval over 250 ms (tab back, breakpoint) is not counted and the count starts again", () => {
  const watch = createFrameWatch();
  feed(watch, 30, 60); // 1.8 s of slow frames
  assert.equal(watch.step(251), false, "over the gap: dropped");
  assert.equal(watch.span, 0, "and the count is over");
  assert.equal(feed(watch, 30, 60), false, "1.8 s again: not a full window since the restart");
  const edge = createFrameWatch();
  assert.equal(edge.step(250), false);
  assert.equal(edge.span, 250, "exactly 250 ms is still a frame, not a gap");
  edge.step(251);
  assert.equal(edge.span, 0, "251 ms is a gap");
  const gapped = createFrameWatch();
  feed(gapped, 30, 30);
  gapped.step(5000);
  assert.equal(feed(gapped, 30, 60), false, "a long hidden spell in the middle breaks continuity");
  assert.equal(feed(gapped, 30, 10), true, "and it takes a whole new 2 s to trigger");
});

test("watch: a zero or odd interval (the loop has just started) restarts and never triggers", () => {
  const watch = createFrameWatch();
  feed(watch, 30, 60);
  for (const bad of [0, -5, NaN, Infinity, undefined]) assert.equal(watch.step(bad), false);
  assert.equal(watch.span, 0);
});
