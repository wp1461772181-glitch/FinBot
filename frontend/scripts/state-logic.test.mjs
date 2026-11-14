import assert from "node:assert/strict";
import test from "node:test";
import { createConfirmQueue } from "../src/confirm-queue.mjs";
import { createTaskRegistry, formatElapsed } from "../src/task-registry.mjs";
import { HOLD_MS, holdProgress, initialHold, stepHold } from "../src/hold-confirm.mjs";

// ---- confirm queue ----
test("an ask resolves true on confirm and false on cancel, and shows only the front of the queue", async () => {
  const queue = createConfirmQueue();
  queue.attachHost(true);
  const seen = []; queue.subscribe(() => seen.push(queue.getSnapshot()?.title ?? null));
  const first = queue.ask({ title: "A" }), second = queue.ask({ title: "B" });
  assert.equal(queue.getSnapshot().title, "A");
  assert.equal(queue.size(), 2);
  queue.answer(true);
  assert.equal(await first, true);
  assert.equal(queue.getSnapshot().title, "B");
  queue.answer(false);
  assert.equal(await second, false);
  assert.equal(queue.getSnapshot(), null);
  assert.deepEqual(seen, ["A", "B", null]);
});

test("with no dialog host an ask is cancelled, never left hanging or approved", async () => {
  const queue = createConfirmQueue();
  assert.equal(await queue.ask({ title: "A" }), false);
  queue.attachHost(true);
  const waiting = queue.ask({ title: "B" });
  queue.attachHost(false);
  assert.equal(await waiting, false);
  assert.equal(queue.getSnapshot(), null);
});

test("answering with nothing on screen is harmless", () => {
  const queue = createConfirmQueue();
  queue.attachHost(true);
  queue.answer(true);
  assert.equal(queue.getSnapshot(), null);
});

// ---- task registry ----
test("tasks register, change stage, finish and announce the finish once", () => {
  let t = 0;
  const registry = createTaskRegistry({ now: () => t });
  const finished = []; registry.onFinish((event) => finished.push(event));
  const task = registry.start({ id: "scan", label: "扫描", stage: "读取" });
  assert.equal(registry.getSnapshot().length, 1);
  const before = registry.getSnapshot();
  t = 7000; task.setStage("解析");
  assert.notEqual(registry.getSnapshot(), before);
  assert.equal(registry.getSnapshot()[0].stage, "解析");
  assert.equal(registry.elapsedMs(registry.getSnapshot()[0]), 7000);
  t = 9000; task.done("完成");
  task.done("again");
  assert.equal(registry.getSnapshot().length, 0);
  assert.equal(finished.length, 1);
  assert.deepEqual({ ok: finished[0].ok, message: finished[0].message, elapsedMs: finished[0].elapsedMs, label: finished[0].task.label }, { ok: true, message: "完成", elapsedMs: 9000, label: "扫描" });
});

test("a task that fails reports ok=false, and starting an id again updates it instead of duplicating", () => {
  const registry = createTaskRegistry({ now: () => 0 });
  const finished = []; registry.onFinish((event) => finished.push(event));
  registry.start({ id: "x", label: "L", stage: "1" });
  const again = registry.start({ id: "x", label: "L", stage: "2" });
  assert.equal(registry.getSnapshot().length, 1);
  assert.equal(registry.getSnapshot()[0].stage, "2");
  again.fail("没成功");
  assert.equal(finished[0].ok, false);
});

test("elapsed time reads m:ss, then h:mm:ss", () => {
  assert.equal(formatElapsed(0), "0:00");
  assert.equal(formatElapsed(7400), "0:07");
  assert.equal(formatElapsed(65000), "1:05");
  assert.equal(formatElapsed(3723000), "1:02:03");
  assert.equal(formatElapsed(-5), "0:00");
});

// ---- hold to confirm ----
test("a hold completes only after the full time, and letting go earlier starts over", () => {
  let s = stepHold(initialHold(), { type: "press", via: "pointer", now: 0 });
  assert.equal(s.phase, "holding");
  assert.equal(holdProgress(s, 250), 0.25);
  s = stepHold(s, { type: "tick", now: HOLD_MS - 1 });
  assert.equal(s.phase, "holding");
  s = stepHold(s, { type: "release" });
  assert.equal(s.phase, "idle");
  s = stepHold(s, { type: "press", via: "key", now: 5000 });
  s = stepHold(s, { type: "press", via: "key", now: 5100 });   // auto-repeat does not restart the hold
  assert.equal(s.since, 5000);
  s = stepHold(s, { type: "tick", now: 5000 + HOLD_MS });
  assert.equal(s.phase, "done");
  assert.equal(holdProgress(s, 99999), 1);
});

test("reduced motion turns the hold into press twice; the second press must come soon enough", () => {
  const opts = { reducedMotion: true };
  let s = stepHold(initialHold(), { type: "press", via: "pointer", now: 0 }, opts);
  assert.equal(s.phase, "armed");
  s = stepHold(s, { type: "press", via: "pointer", now: 1000 }, opts);
  assert.equal(s.phase, "done");
  s = stepHold(initialHold(), { type: "press", via: "key", now: 0 }, opts);
  s = stepHold(s, { type: "tick", now: 5000 }, opts);
  assert.equal(s.phase, "idle", "disarmed after the arming time");
  s = stepHold(stepHold(initialHold(), { type: "press", via: "key", now: 0 }, opts), { type: "press", via: "key", now: 6000 }, opts);
  assert.equal(s.phase, "armed", "a late second press only re-arms");
});

test("a click that came with no press (assistive technology) is press-twice, and blur disarms", () => {
  let s = stepHold(initialHold(), { type: "click", now: 0 });
  assert.equal(s.phase, "armed");
  assert.equal(stepHold(s, { type: "blur" }).phase, "idle");
  s = stepHold(s, { type: "click", now: 500 });
  assert.equal(s.phase, "done");
  assert.equal(stepHold(s, { type: "blur" }).phase, "done", "a finished confirm is not undone by blur");
});
