import test from "node:test";
import assert from "node:assert/strict";
import { bindRowGaze, rowAim } from "../src/row-gaze.mjs";

// A host with just enough of EventTarget to count live listeners.
function fakeHost() {
  const map = new Map();
  return {
    addEventListener(type, fn) { (map.get(type) ?? map.set(type, new Set()).get(type)).add(fn); },
    removeEventListener(type, fn) { map.get(type)?.delete(fn); },
    fire(type, e = {}) { for (const fn of [...(map.get(type) ?? [])]) fn({ pointerType: "mouse", clientX: 0, clientY: 0, ...e }); },
    count() { let n = 0; for (const s of map.values()) n += s.size; return n; }
  };
}
const setup = (opts = {}) => {
  const host = fakeHost(), handle = { pointer: null }, active = [];
  let t = 100;
  const dispose = bindRowGaze(host, { handle, setActive: v => active.push(v), now: () => t, reduced: () => false, ...opts });
  return { host, handle, active, dispose, tick: v => { t = v; } };
};

test("only the pointerenter listener exists until the pointer enters the row", () => {
  const { host } = setup();
  assert.equal(host.count(), 1);
});

test("entering starts following; moving writes the pointer; no state update per move", () => {
  const { host, handle, active, tick } = setup();
  host.fire("pointerenter", { clientX: 5, clientY: 6 });
  assert.deepEqual(active, [true]);
  assert.deepEqual(handle.pointer, { x: 5, y: 6, at: 100 });
  tick(101); host.fire("pointermove", { clientX: 40, clientY: 9 });
  host.fire("pointermove", { clientX: 41, clientY: 9 });
  assert.deepEqual(handle.pointer, { x: 41, y: 9, at: 101 });
  assert.deepEqual(active, [true]);
});

test("leaving releases the gaze and drops the move/leave listeners", () => {
  const { host, handle, active } = setup();
  host.fire("pointerenter");
  assert.ok(host.count() > 1);
  host.fire("pointerleave");
  assert.equal(handle.pointer, null);
  assert.deepEqual(active, [true, false]);
  assert.equal(host.count(), 1);
  host.fire("pointerenter"); host.fire("pointerleave"); // re-entering works, and never stacks listeners
  assert.equal(host.count(), 1);
});

test("dispose while hovered releases and removes every listener (row unmount)", () => {
  const { host, handle, active, dispose } = setup();
  host.fire("pointerenter");
  dispose();
  assert.equal(host.count(), 0);
  assert.equal(handle.pointer, null);
  assert.deepEqual(active, [true, false]);
  dispose(); // idempotent
  assert.equal(host.count(), 0);
});

test("dispose when never hovered does not report a release", () => {
  const { host, active, dispose } = setup();
  dispose();
  assert.equal(host.count(), 0);
  assert.deepEqual(active, []);
});

test("touch pointers never start the gaze; reduced motion binds nothing", () => {
  const t = setup();
  t.host.fire("pointerenter", { pointerType: "touch" });
  assert.deepEqual(t.active, []);
  assert.equal(t.handle.pointer, null);
  const r = setup({ reduced: () => true });
  assert.equal(r.host.count(), 0);
});

test("a touch move during a hover does not overwrite the mouse pointer", () => {
  const { host, handle } = setup();
  host.fire("pointerenter", { clientX: 1, clientY: 1 });
  host.fire("pointermove", { pointerType: "touch", clientX: 99, clientY: 99 });
  assert.equal(handle.pointer.x, 1);
});

const box = { left: 0, top: 0, width: 40, height: 40 }, view = { width: 1000, height: 800 };
test("rowAim follows only an idle base with a fresh pointer", () => {
  const p = { x: 300, y: 20, at: 10 };
  assert.ok(rowAim(p, "idle", 11, box, view));
  assert.equal(rowAim(p, "orbit", 11, box, view), null);   // work: state machine wins
  assert.equal(rowAim(p, "notify", 11, box, view), null);  // unread: state machine wins
  assert.equal(rowAim(p, "idle", 14, box, view), null);    // pointer stopped: released
  assert.equal(rowAim(null, "idle", 11, box, view), null);
});
