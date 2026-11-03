import test from "node:test";
import assert from "node:assert/strict";
import { T, createDirector, shouldArrive, turnPhase, turnTransition } from "../src/bloub-director.mjs";

const states = (d, times) => times.map(t => d.read(t).state);

test("a sent message: notice -> orbit while waiting -> done stinger -> idle", () => {
  const d = createDirector({ now: 0 });
  assert.equal(d.read(0).state, "idle");
  d.send({ type: "turn-start" }, 10);
  assert.deepEqual(states(d, [10, 10.5]), ["wide", "wide"]);
  assert.equal(d.read(10 + T.ATTENTION + 0.01).state, "orbit");
  d.send({ type: "turn-end", outcome: "done" }, 14);
  assert.equal(d.read(14.7).state, "wink");
  assert.equal(d.read(14 + T.SUCCESS + 0.01).state, "idle");
});

test("tool steps show orbit, answer generation shows thinking, back to orbit on a new tool", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "phase", phase: "tool" }, 2);
  assert.equal(d.read(2.1).state, "orbit");
  d.send({ type: "phase", phase: "answer" }, 5);
  assert.equal(d.read(5.1).state, "thinking");
  d.send({ type: "phase", phase: "tool" }, 8);
  assert.equal(d.read(8.1).state, "orbit");
  assert.equal(d.read(8.1).layer, "work");
});

test("an error turn flashes alert for its full minimum duration, then lands on idle", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "turn-end", outcome: "error" }, 3);
  assert.equal(d.read(3.1).state, "alert");
  assert.equal(d.read(3 + T.ERROR - 0.05).state, "alert");
  assert.ok(T.ERROR >= 2, "alert is cut before the exclamation mark returns under 2 s");
  assert.equal(d.read(3 + T.ERROR + 0.01).state, "idle");
});

test("a cancelled turn just drops back to idle, no stinger", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "turn-end", outcome: "cancel" }, 5);
  assert.equal(d.read(5.7).state, "idle");
});

test("priority: work > notification > reaction > life > idle", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "unread", value: true }, 1);
  assert.deepEqual([d.read(1.7).state, d.read(1.7).layer], ["notify", "notify"]);
  d.send({ type: "click" }, 2);          // a reaction never beats the notification
  assert.equal(d.read(2.7).state, "notify");
  d.send({ type: "turn-start" }, 3);     // work beats the notification
  assert.equal(d.read(3.7).layer, "work");
  d.send({ type: "turn-end", outcome: "cancel" }, 8);
  assert.equal(d.read(8.7).state, "notify"); // notification is still waiting after the work
  d.send({ type: "unread", value: false }, 9);
  assert.equal(d.read(9.7).state, "idle");
});

test("hover and click reactions never interrupt a running turn", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "phase", phase: "tool" }, 1);
  d.send({ type: "hover", value: true }, 2);
  d.send({ type: "click" }, 3);
  assert.equal(d.read(3.1).state, "orbit");
  d.send({ type: "phase", phase: "answer" }, 4);
  assert.equal(d.read(4.7).state, "thinking");
});

test("a turn pre-empts a reaction that is already playing", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "click" }, 1);
  assert.equal(d.read(1.7).state, "burst");
  d.send({ type: "turn-start" }, 2);
  assert.equal(d.read(2.7).layer, "work");
  assert.equal(d.read(2.7).state, "wide");
});

test("hover: a small reaction that ends on leave (after the engine's morph floor) or after its hold", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "hover", value: true }, 1);
  assert.equal(d.read(1).state, "wide");
  d.send({ type: "hover", value: false }, 1.1); // left earlier than the morph floor: held, not cut
  assert.equal(d.read(1.3).state, "wide");
  assert.equal(d.read(1 + T.DWELL + 0.01).state, "idle");
  d.send({ type: "hover", value: true }, 5);
  assert.equal(d.read(5 + T.HOVER + 0.05).state, "idle"); // still hovering, but it does not stare forever
  assert.equal(d.read(5 + T.HOVER + 5).state, "idle");
});

test("click plays burst then comet alternately and returns to idle by itself", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "click" }, 1);
  assert.equal(d.read(1.7).state, "burst");
  assert.equal(d.read(1 + T.CLICK + 0.01).state, "idle");
  d.send({ type: "click" }, 10);
  assert.equal(d.read(10.7).state, "comet");
});

test("a click during hover wins; hover does not restart after the click ends", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "hover", value: true }, 1);
  d.send({ type: "click" }, 1.8);
  assert.equal(d.read(2.5).state, "burst");
  assert.equal(d.read(1.8 + T.CLICK + 0.7).state, "idle");
});

test("sleep after the idle threshold, any interaction wakes it", () => {
  const d = createDirector({ now: 0 });
  assert.equal(d.read(T.SLEEP_AFTER - 1).state, "idle");
  assert.equal(d.read(T.SLEEP_AFTER + 1).state, "sleep");
  assert.equal(d.read(T.SLEEP_AFTER + 1).layer, "life");
  d.send({ type: "activity" }, T.SLEEP_AFTER + 2);
  assert.equal(d.read(T.SLEEP_AFTER + 2.7).state, "idle");
  assert.equal(d.read(T.SLEEP_AFTER + 2 + T.SLEEP_AFTER - 1).state, "idle");
});

test("a finished turn counts as activity: no nap right after answering", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 50);
  d.send({ type: "turn-end", outcome: "done" }, 100);
  assert.equal(d.read(100 + T.SUCCESS + 1).state, "idle");
});

test("unread notification outranks sleep", () => {
  const d = createDirector({ now: 0 });
  assert.equal(d.read(T.SLEEP_AFTER + 5).state, "sleep");
  d.send({ type: "unread", value: true }, T.SLEEP_AFTER + 6);
  assert.equal(d.read(T.SLEEP_AFTER + 7).state, "notify");
});

test("no state change faster than the engine's longest morph", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "turn-end", outcome: "done" }, 0.1); // answer instantly
  const seen = [];
  for (let t = 0; t < 6; t += 0.05) { const s = d.read(t).state; if (seen.at(-1)?.[1] !== s) seen.push([t, s]); }
  for (let i = 1; i < seen.length; i++) assert.ok(seen[i][0] - seen[i - 1][0] >= T.DWELL - 1e-9, JSON.stringify(seen));
});

test("follow and intro flags only exist while idle", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "arrive" }, 1);
  assert.deepEqual([d.read(1.5).intro, d.read(1.5).follow], [true, true]);
  assert.equal(d.read(1 + T.INTRO + 0.1).intro, false);
  d.send({ type: "turn-start" }, 5);
  assert.deepEqual([d.read(5.7).follow, d.read(5.7).intro], [false, false]);
  d.send({ type: "turn-end", outcome: "cancel" }, 6);
  d.send({ type: "click" }, 8);
  assert.equal(d.read(8.7).follow, false);
  assert.equal(d.read(T.SLEEP_AFTER + 20).follow, false);
});

test("reduced motion: no reactions, intro, sleep or follow; work and notification stay (as still frames)", () => {
  const d = createDirector({ now: 0, reducedMotion: true });
  d.send({ type: "arrive" }, 1);
  d.send({ type: "hover", value: true }, 1);
  d.send({ type: "click" }, 2);
  assert.deepEqual([d.read(3).state, d.read(3).intro, d.read(3).follow], ["idle", false, false]);
  assert.equal(d.read(T.SLEEP_AFTER + 30).state, "idle");
  d.send({ type: "turn-start" }, 100);
  assert.equal(d.read(101).state, "orbit"); // no attention stinger either way: still shows the work state
  d.send({ type: "turn-end", outcome: "cancel" }, 105);
  d.send({ type: "unread", value: true }, 106);
  assert.equal(d.read(107).state, "notify");
});

test("arrival plays once per bot per session, never under reduced motion", () => {
  const seen = new Set();
  assert.equal(shouldArrive(seen, "bot-a", false), true);
  assert.equal(shouldArrive(seen, "bot-a", false), false);
  assert.equal(shouldArrive(seen, "bot-b", false), true);
  assert.equal(shouldArrive(seen, "bot-c", true), false);
  assert.equal(shouldArrive(seen, "bot-c", false), true); // reduced motion did not consume it
  assert.equal(shouldArrive(seen, "", false), false);
});

test("turnPhase reads the streaming transcript", () => {
  assert.equal(turnPhase("ready", []), null);
  assert.equal(turnPhase("sending", [{ role: "user", content: "hi" }]), "waiting");
  assert.equal(turnPhase("sending", [{ role: "user" }, { role: "assistant", content: "", tool_trace: [{ status: "running" }] }]), "tool");
  assert.equal(turnPhase("sending", [{ role: "user" }, { role: "assistant", content: "", tool_trace: [{ status: "complete" }] }]), "tool");
  assert.equal(turnPhase("sending", [{ role: "user" }, { role: "assistant", content: "Sure", tool_trace: [{ status: "complete" }] }]), "answer");
  assert.equal(turnPhase("sending", [{ role: "user" }, { role: "assistant", content: "Sure", tool_trace: [{ status: "running" }] }]), "tool");
});

test("turnTransition maps chat state changes to director events", () => {
  const ok = [{ role: "user" }, { role: "assistant", content: "x", status: "complete" }];
  assert.deepEqual(turnTransition("ready", "sending", []), { type: "turn-start" });
  assert.deepEqual(turnTransition("sending", "ready", ok), { type: "turn-end", outcome: "done" });
  assert.deepEqual(turnTransition("sending", "error", ok), { type: "turn-end", outcome: "error" });
  assert.deepEqual(turnTransition("sending", "ready", [{ role: "user" }, { role: "assistant", status: "cancelled" }]), { type: "turn-end", outcome: "cancel" });
  assert.deepEqual(turnTransition("sending", "ready", [{ role: "user" }]), { type: "turn-end", outcome: "cancel" });
  assert.equal(turnTransition("ready", "ready", ok), null);
  assert.equal(turnTransition("sending", "sending", ok), null);
});

test("a quiet turn start (remounting onto a running turn) skips the attention beat", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start", quiet: true }, 5);
  d.send({ type: "phase", phase: "answer" }, 5);
  assert.equal(d.read(5.1).state, "thinking");
});
