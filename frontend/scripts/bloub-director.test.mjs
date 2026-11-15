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

// A1 changed this test: a running tool is no longer an orbit (design 6.3, fixes A3: waiting and tool had the same body). It is the idle body, on the work layer.
test("tool steps show the idle body (work layer), answer generation shows thinking, back to the idle body on a new tool", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "phase", phase: "tool" }, 2);
  assert.equal(d.read(2.1).state, "idle");
  assert.equal(d.read(2.1).layer, "work");
  d.send({ type: "phase", phase: "answer" }, 5);
  assert.equal(d.read(5.1).state, "thinking");
  d.send({ type: "phase", phase: "tool" }, 8);
  assert.equal(d.read(8.1).state, "idle");
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
  assert.equal(d.read(3.1).state, "idle"); // A1: the tool body (was orbit) ...
  assert.equal(d.read(3.1).layer, "work"); // ... still on the work layer: no hover "wide", no burst / comet
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

// --- A0: waiting for you and partial success are not a success -------------------------------------------------
const CARD = { request_id: "0b9f7f64-6b1f-4a40-9a55-0d2f4d3b7a10", reason: "write_confirmation", choices: [{ label: "确认", value: "confirm:1" }] };
const lastOf = (status, extra = {}) => [{ role: "user", content: "q" }, { role: "assistant", content: "a", status, ...extra }];
/** Run a whole turn that ends with `outcome` at t = 10 and report every state it shows afterwards. */
function statesAfter(outcome) {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "phase", phase: "answer" }, 3);
  d.send({ type: "turn-end", outcome }, 10);
  const seen = [];
  for (let t = 10; t <= 20; t += 0.05) seen.push(d.read(t));
  return seen;
}

test("turnTransition: waiting statuses and an unanswered card end a turn as 'waiting'", () => {
  for (const status of ["waiting_for_input", "waiting_for_user"]) {
    assert.deepEqual(turnTransition("sending", "ready", lastOf(status)), { type: "turn-end", outcome: "waiting" }, status);
  }
  assert.deepEqual(turnTransition("sending", "ready", lastOf("waiting_for_input", { clarification: CARD })), { type: "turn-end", outcome: "waiting" });
  // a card on a message whose status is not a waiting one still needs an answer
  assert.deepEqual(turnTransition("sending", "ready", lastOf("complete", { clarification: CARD })), { type: "turn-end", outcome: "waiting" });
  assert.deepEqual(turnTransition("sending", "ready", lastOf(undefined, { clarification: CARD })), { type: "turn-end", outcome: "waiting" });
});

test("turnTransition: partially_succeeded is 'partial'; succeeded / complete stay 'done'", () => {
  assert.deepEqual(turnTransition("sending", "ready", lastOf("partially_succeeded")), { type: "turn-end", outcome: "partial" });
  for (const status of ["succeeded", "complete", undefined]) {
    assert.deepEqual(turnTransition("sending", "ready", lastOf(status)), { type: "turn-end", outcome: "done" }, String(status));
  }
});

test("turnTransition precedence: error > cancel > waiting > partial > done", () => {
  assert.equal(turnTransition("sending", "ready", lastOf("failed", { clarification: CARD })).outcome, "error"); // failed beats a card
  assert.equal(turnTransition("sending", "error", lastOf("waiting_for_input", { clarification: CARD })).outcome, "error"); // chat error beats everything
  assert.equal(turnTransition("sending", "ready", lastOf("cancelled", { clarification: CARD })).outcome, "cancel"); // cancelled beats a card
  assert.equal(turnTransition("sending", "ready", lastOf("cancelled")).outcome, "cancel");
  assert.equal(turnTransition("sending", "ready", lastOf("partially_succeeded", { clarification: CARD })).outcome, "waiting"); // waiting beats partial
  assert.equal(turnTransition("sending", "ready", [{ role: "user" }]).outcome, "cancel");
});

test("a turn that ends waiting never winks, at any moment afterwards", () => {
  const seen = statesAfter("waiting");
  assert.ok(seen.every(v => v.state !== "wink"), "no wink");
  assert.equal(seen.at(-1).state, "idle");
  assert.equal(seen.at(-1).layer, "work"); // A1: waiting-for-you is a work pose of its own (design 6.3), not a fall back to the idle layer
  assert.equal(seen.at(-1).waitingForUser, true);
});

test("end to end through turnTransition: waiting_for_input / waiting_for_user / an unanswered card never produce a wink", () => {
  const cases = [lastOf("waiting_for_input"), lastOf("waiting_for_user"), lastOf("complete", { clarification: CARD })];
  for (const messages of cases) {
    const d = createDirector({ now: 0 });
    d.send(turnTransition("ready", "sending", []), 0);
    d.send({ type: "phase", phase: "answer" }, 3);
    const end = turnTransition("sending", "ready", messages);
    assert.equal(end.outcome, "waiting");
    d.send(end, 10);
    for (let t = 10; t <= 20; t += 0.05) assert.notEqual(d.read(t).state, "wink", `t=${t}`);
    assert.equal(d.read(11).ended, "waiting");
  }
});

test("a turn that ends partially_succeeded never winks and is readable as ended 'partial' for T.PARTIAL", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "turn-end", outcome: turnTransition("sending", "ready", lastOf("partially_succeeded")).outcome }, 10);
  for (let t = 10; t <= 20; t += 0.05) assert.notEqual(d.read(t).state, "wink", `t=${t}`);
  assert.equal(d.read(10.1).ended, "partial");
  assert.equal(d.read(10 + T.PARTIAL - 0.05).ended, "partial");
  assert.equal(d.read(10 + T.PARTIAL + 0.05).ended, null);
});

test("partial falls back to the next priority: unread shows notify, otherwise idle", () => {
  for (const outcome of ["partial"]) {
    const d = createDirector({ now: 0 });
    d.send({ type: "unread", value: true }, 1);
    d.send({ type: "turn-start" }, 2);
    d.send({ type: "turn-end", outcome }, 8);
    assert.equal(d.read(8 + T.DWELL + 0.05).state, "notify", outcome);
    d.send({ type: "unread", value: false }, 9);
    assert.equal(d.read(9 + T.DWELL + 0.05).state, "idle", outcome);
  }
});

// A1 changed the "waiting" half of the test above: the priority list is work (incl. waiting-for-you) > unread (design 6.3), so a
// turn that ends waiting keeps its own pose over an unread notification, and notify shows once the card is cleared.
test("waiting-for-you outranks unread; once it is cleared the unread notification shows", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "unread", value: true }, 1);
  d.send({ type: "turn-start" }, 2);
  d.send({ type: "turn-end", outcome: "waiting" }, 8);
  const held = d.read(8 + T.DWELL + 0.05);
  assert.equal(held.state, "idle"); assert.equal(held.layer, "work"); assert.equal(held.waitingForUser, true);
  d.send({ type: "waiting-clear" }, 20);
  assert.equal(d.read(20 + T.DWELL + 0.05).state, "notify");
  assert.equal(d.read(20 + T.DWELL + 0.05).waitingForUser, false);
});

test("'ended: waiting' lasts until the next turn starts; other outcomes leave ended null", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "turn-end", outcome: "waiting" }, 5);
  assert.equal(d.read(6).ended, "waiting");
  assert.equal(d.read(500).ended, "waiting");
  d.send({ type: "turn-start" }, 501);
  assert.equal(d.read(501.1).ended, null);
  for (const outcome of ["done", "error", "cancel"]) {
    const e = createDirector({ now: 0 });
    e.send({ type: "turn-start" }, 0);
    e.send({ type: "turn-end", outcome }, 5);
    assert.equal(e.read(5.1).ended, null, outcome);
  }
});

test("regression: succeeded / complete still wink for T.SUCCESS, then idle", () => {
  for (const status of ["succeeded", "complete"]) {
    const d = createDirector({ now: 0 });
    d.send(turnTransition("ready", "sending", []), 0);
    const end = turnTransition("sending", "ready", lastOf(status));
    assert.equal(end.outcome, "done");
    d.send(end, 10);
    assert.equal(d.read(10.7).state, "wink");
    assert.equal(d.read(10 + T.SUCCESS - 0.05).state, "wink");
    assert.equal(d.read(10 + T.SUCCESS + 0.01).state, "idle");
    assert.equal(d.read(10.7).ended, null);
  }
});

// ---- A1: personalities, new poses ---------------------------------------------------------------------------------------------------
import { bodyTable } from "../src/bloub-director.mjs";
import { MOODS_BY_ARCHETYPE, HOLD } from "../src/bloub-mood.mjs";

const persona = (archetype, extra = {}) => ({ archetype, tempo: 1, easing: "smooth", restGaze: "follow", auraVariant: "ticks", ...extra });
const running = (d, t0 = 0) => { d.send({ type: "turn-start", quiet: true }, t0); return d; };

test("click reactions by archetype (6.5): lead burst/comet in turn, tracker-fast comet, tracker-calm wink, sentinel exclaim, reader wide", () => {
  const first = (p) => { const d = createDirector({ now: 0, persona: p }); d.send({ type: "click" }, 1); return d.read(1.7).state; };
  assert.equal(first(persona("lead")), "burst");
  assert.equal(first(persona("tracker", { auraVariant: "speed-lines" })), "comet");
  assert.equal(first(persona("tracker", { auraVariant: "halo" })), "wink");
  assert.equal(first(persona("sentinel")), "exclaim");
  assert.equal(first(persona("reader")), "wide");
  assert.equal(first(persona("generalist")), "burst");
  assert.equal(first(persona("tracker", { auraVariant: "reticle" })), "burst");
  // the lead alternates; a one-reaction archetype repeats itself
  const d = createDirector({ now: 0, persona: persona("lead") });
  d.send({ type: "click" }, 1); d.send({ type: "click" }, 10);
  assert.equal(d.read(10.7).state, "comet");
  const s = createDirector({ now: 0, persona: persona("sentinel") });
  s.send({ type: "click" }, 1); s.send({ type: "click" }, 10);
  assert.equal(s.read(10.7).state, "exclaim");
  // the table is a table: every archetype has all the keys of the default, and only the click differs
  for (const a of ["lead", "tracker", "sentinel", "reader", "generalist"]) assert.deepEqual(Object.keys(bodyTable(persona(a))).sort(), Object.keys(bodyTable()).sort());
  // a short reaction ends at its own length, not at the burst's 2.4 s
  const r = createDirector({ now: 0, persona: persona("reader") });
  r.send({ type: "click" }, 1);
  assert.equal(r.read(1 + T.HOVER + 0.1).state, "idle");
  const e = createDirector({ now: 0, persona: persona("sentinel") });
  e.send({ type: "click" }, 1);
  assert.equal(e.read(1 + 1.8 - 0.05).state, "exclaim");
});

test("every archetype keeps the same time skeleton: the stinger lengths do not scale with tempo", () => {
  const lastStinger = (d, from, state) => { let last = null; for (let t = from; t < from + 5; t += 0.05) if (d.read(t).state === state) last = t; return last - from; };
  for (const tempo of [0.8, 1, 1.25]) {
    const d = createDirector({ now: 0, persona: persona("lead", { tempo }) });
    running(d); d.send({ type: "turn-end", outcome: "done" }, 5);
    assert.ok(Math.abs(lastStinger(d, 5, "wink") - T.SUCCESS) < 0.1, `done at tempo ${tempo}`);
    const e = createDirector({ now: 0, persona: persona("lead", { tempo }) });
    running(e); e.send({ type: "turn-end", outcome: "error" }, 5);
    assert.ok(Math.abs(lastStinger(e, 5, "alert") - T.ERROR) < 0.1, `error at tempo ${tempo}`);
  }
  const d = createDirector({ now: 0, persona: persona("reader", { tempo: 0.8, easing: "step" }) });
  const view = d.read(0);
  assert.equal(view.tempo, 0.8); assert.equal(view.easing, "step"); assert.equal(view.archetype, "reader");
});

test("the face rotation runs at the persona's tempo; the sequence is the archetype's", () => {
  const slow = createDirector({ now: 0, persona: persona("sentinel", { tempo: 0.8 }) }), fast = createDirector({ now: 0, persona: persona("sentinel", { tempo: 1.25 }) });
  for (const d of [slow, fast]) { running(d, 0); d.send({ type: "phase", phase: "tool" }, 0.01); }
  const seq = MOODS_BY_ARCHETYPE.sentinel.tool;
  assert.equal(slow.read(HOLD + 0.2).expression, seq[0], "0.8 x: still on the first face after one hold");
  assert.equal(fast.read(HOLD + 0.2).expression, seq[1], "1.25 x: already on the second");
  const lead = createDirector({ now: 0, persona: persona("lead") });
  running(lead); lead.send({ type: "phase", phase: "tool" }, 0.01);
  assert.equal(lead.read(0.2).expression, MOODS_BY_ARCHETYPE.lead.tool[0]);
  assert.equal(slow.read(0.2).expression, seq[0]);
});

test("listening: the composer has text and no turn runs -> idle body, looking down, focused face; stops when the text goes", () => {
  const d = createDirector({ now: 0 });
  assert.equal(d.read(1).pose, "idle");
  d.send({ type: "phase", phase: "listening" }, 2);
  const v = d.read(2.1);
  assert.deepEqual([v.state, v.pose, v.gaze, v.follow, v.expression], ["idle", "listen", "below", false, "attentif"]);
  d.send({ type: "phase", phase: "idle" }, 5);
  const back = d.read(5.1);
  assert.deepEqual([back.pose, back.gaze, back.follow, back.expression], ["idle", "follow", true, "neutre"]);
  // a running turn is not a listening one; starting a turn drops the listening pose
  d.send({ type: "phase", phase: "listening" }, 6);
  d.send({ type: "turn-start", quiet: true }, 7);
  assert.equal(d.read(7.1).pose, "waiting");
  d.send({ type: "turn-end", outcome: "done" }, 9);
  assert.equal(d.read(9 + T.SUCCESS + T.DWELL + 0.1).pose, "idle", "the pose from before the turn did not come back by itself");
  // "listening" sent during a turn is ignored; unread outranks listening
  const e = createDirector({ now: 0 });
  running(e); e.send({ type: "phase", phase: "listening" }, 1);
  assert.equal(e.read(1.1).pose, "waiting");
  const u = createDirector({ now: 0 });
  u.send({ type: "phase", phase: "listening" }, 1); u.send({ type: "unread", value: true }, 2);
  assert.equal(u.read(2.1).state, "notify");
});

test("work poses (6.3): waiting = orbit; tool = idle body looking toward its aura; verify = idle body looking down; answer = thinking", () => {
  const d = running(createDirector({ now: 0 }));
  const at = (phase, t) => { d.send({ type: "phase", phase }, t); return d.read(t + 0.7); };
  const waiting = d.read(0.7);
  assert.deepEqual([waiting.state, waiting.layer], ["orbit", "work"]);
  const tool = at("tool", 2);
  assert.deepEqual([tool.state, tool.layer, tool.gaze, tool.follow, tool.expression], ["idle", "work", "sweep", false, MOODS_BY_ARCHETYPE.lead.tool[0]]); // the dial turns: the eyes follow its point (A2; was "side")
  const verify = at("verify", 5);
  assert.deepEqual([verify.state, verify.layer, verify.gaze, verify.follow, verify.expression], ["idle", "work", "below", false, "mefiant"]);
  assert.notEqual(tool.state, waiting.state, "waiting and tool are no longer the same body (A3)");
  const answer = at("answer", 8);
  assert.deepEqual([answer.state, answer.expression], ["thinking", MOODS_BY_ARCHETYPE.lead.answer[0]]);
  const again = at("thinking", 11); // the signal's name for "waiting"
  assert.equal(again.state, "orbit");
  // an unknown phase changes nothing
  d.send({ type: "phase", phase: "bogus" }, 13);
  assert.equal(d.read(13.7).state, "orbit");
});

test("waiting for you: idle body, eyes front, amber dot; a `wide` every 6 s, three times, then still; never a wink", () => {
  const d = running(createDirector({ now: 0 }));
  d.send({ type: "turn-end", outcome: "waiting" }, 10);
  const first = d.read(10 + T.DWELL + 0.1);
  assert.deepEqual([first.state, first.layer, first.pose, first.gaze, first.follow, first.waitingForUser, first.ended, first.expression], ["idle", "work", "hold", "front", false, true, "waiting", "attentif"]);
  assert.equal(first.frozen, false);
  const nudges = [];
  let prev = "idle";
  for (let t = 10; t <= 60; t += 0.05) {
    const v = d.read(t);
    assert.notEqual(v.state, "wink");
    assert.equal(v.waitingForUser, true, "the dot stays up the whole time, no blinking");
    if (v.state === "wide" && prev !== "wide") nudges.push(Math.round((t - 10) * 10) / 10);
    prev = v.state;
  }
  assert.equal(nudges.length, T.NUDGE_MAX, `exactly ${T.NUDGE_MAX} nudges: ${nudges}`);
  nudges.forEach((t, i) => assert.ok(Math.abs(t - T.NUDGE_EVERY * (i + 1)) < 0.2, `nudge ${i} at ${t}`));
  const late = d.read(60);
  assert.equal(late.frozen, true, "after the third nudge it is a still frame: no more frames computed");
  assert.equal(late.state, "idle");
  // it never goes to sleep while it waits for you, however long
  assert.equal(d.read(5000).state, "idle");
  assert.equal(d.read(5000).waitingForUser, true);
});

test("waiting for you is cleared by the card running out or being answered, and by the next turn", () => {
  for (const clear of [e => e.send({ type: "waiting-clear" }, 30), e => e.send({ type: "turn-start" }, 30)]) {
    const d = running(createDirector({ now: 0 }));
    d.send({ type: "turn-end", outcome: "waiting" }, 10);
    assert.equal(d.read(20).waitingForUser, true);
    clear(d);
    const v = d.read(30 + T.ATTENTION + 0.5);
    assert.equal(v.ended, null); assert.equal(v.waitingForUser, false);
  }
  // clearing a waiting that is not there does nothing; it does not cancel a partial beat
  const d = running(createDirector({ now: 0 }));
  d.send({ type: "turn-end", outcome: "partial" }, 10);
  d.send({ type: "waiting-clear" }, 10.1);
  assert.equal(d.read(10.2).ended, "partial");
});

test("partial: no wink, a nod of progress 0..1 over T.PARTIAL on whatever body is shown, then nothing", () => {
  const d = running(createDirector({ now: 0 }));
  d.send({ type: "turn-end", outcome: "partial" }, 10);
  assert.equal(d.read(10).nod, 0);
  const mid = d.read(10 + T.PARTIAL / 2);
  assert.ok(Math.abs(mid.nod - 0.5) < 1e-9);
  assert.equal(mid.waitingForUser, false);
  assert.notEqual(mid.state, "wink");
  assert.equal(d.read(10 + T.PARTIAL + 0.05).nod, null);
  const done = running(createDirector({ now: 0 }));
  done.send({ type: "turn-end", outcome: "done" }, 10);
  assert.equal(done.read(10.5).nod, null);
});

test("offline: a frozen, dimmed idle frame under everything but a running turn; back to normal when it clears", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "offline", value: true }, 5);
  const v = d.read(5.1);
  assert.deepEqual([v.state, v.pose, v.dim, v.frozen, v.follow, v.gaze], ["idle", "offline", true, true, false, "front"]);
  d.send({ type: "unread", value: true }, 6);
  assert.equal(d.read(7).state, "idle", "unread waits");
  d.send({ type: "hover", value: true }, 8); d.send({ type: "click" }, 9);
  assert.equal(d.read(9.5).state, "idle", "no reactions either");
  d.send({ type: "offline", value: false }, 20);
  const back = d.read(21);
  assert.deepEqual([back.state, back.dim, back.frozen], ["notify", false, false]);
  // going offline does not touch the activity clock: it does not wake a sleeper, and a long offline spell does not make it nap on return
  const e = createDirector({ now: 0 });
  e.send({ type: "offline", value: true }, 1000);
  assert.equal(e.read(1001).dim, true);
  // a failed turn plays its alert first (2 s), then the frozen frame
  const f = running(createDirector({ now: 0 }));
  f.send({ type: "offline", value: true }, 1); f.send({ type: "turn-end", outcome: "error" }, 2);
  assert.equal(f.read(2.5).state, "alert");
  assert.equal(f.read(2 + T.ERROR + T.DWELL + 0.1).dim, true);
});

test("sleep freezes after T.SLEEP_FREEZE and any activity wakes it; the wake never reads as frozen", () => {
  const d = createDirector({ now: 0 });
  assert.equal(d.read(T.SLEEP_AFTER + 1).state, "sleep");
  assert.equal(d.read(T.SLEEP_AFTER + 1).frozen, false);
  assert.equal(d.read(T.SLEEP_AFTER + T.SLEEP_FREEZE - 1).frozen, false);
  assert.equal(d.read(T.SLEEP_AFTER + T.SLEEP_FREEZE + 1).frozen, true);
  assert.equal(d.read(T.SLEEP_AFTER + T.SLEEP_FREEZE + 1).state, "sleep");
  d.send({ type: "activity" }, 100);
  const woke = d.read(100.01);
  assert.equal(woke.frozen, false, "inside the dwell the old state is still shown, but the loop must run to leave it");
  assert.equal(d.read(100.8).state, "idle");
  assert.equal(d.read(100.8).frozen, false);
});

test("the face of a still frame: reduced motion keeps `expression` calm but names the face each pose wears", () => {
  const d = createDirector({ now: 0, reducedMotion: true, persona: persona("reader") });
  d.send({ type: "turn-start" }, 1);
  const waiting = d.read(1.1);
  assert.equal(waiting.expression, "neutre"); assert.equal(waiting.still, MOODS_BY_ARCHETYPE.reader.waiting[0]);
  d.send({ type: "phase", phase: "verify" }, 3);
  assert.equal(d.read(3.1).still, MOODS_BY_ARCHETYPE.reader.verify[0]);
  d.send({ type: "turn-end", outcome: "waiting" }, 6);
  const hold = d.read(7);
  assert.equal(hold.waitingForUser, true); assert.equal(hold.still, "attentif");
  for (let t = 7; t < 60; t += 0.5) assert.notEqual(d.read(t).state, "wide", "no nudges under reduced motion");
  assert.equal(d.read(7).frozen, false, "reduced motion has no loop to stop; its still frame is drawn by the owner");
});

test("a persona changes only what it should: with no persona the director is the old one", () => {
  const plain = createDirector({ now: 0 }), lead = createDirector({ now: 0, persona: persona("lead") });
  for (const d of [plain, lead]) { d.send({ type: "turn-start" }, 1); d.send({ type: "phase", phase: "answer" }, 3); d.send({ type: "turn-end", outcome: "done" }, 5); }
  for (let t = 0; t < 12; t += 0.25) assert.deepEqual(plain.read(t), lead.read(t));
});

test("hold: a conversation found waiting (restored, switched to) shows the waiting pose without a turn end; it never replaces a running turn", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "hold" }, 5);
  const v = d.read(5 + T.DWELL + 0.1);
  assert.deepEqual([v.pose, v.waitingForUser, v.ended], ["hold", true, "waiting"]);
  d.send({ type: "hold" }, 20); // a second one does not restart the 6 s nudges
  for (let t = 20; t < 23; t += 0.05) assert.notEqual(d.read(t).state === "wide" && t > 5 + 6.95 && t < 5 + 7.85, true, "no nudge restart");
  d.send({ type: "waiting-clear" }, 30);
  assert.equal(d.read(31).waitingForUser, false);
  const e = running(createDirector({ now: 0 }));
  e.send({ type: "hold" }, 1);
  assert.equal(e.read(1.5).ended, null);
  assert.equal(e.read(1.5).pose, "waiting");
});

test("what the owner reports about the world does not count as the reader being active: no waking, no postponed nap", () => {
  const d = createDirector({ now: 0 });
  // every re-render of the chat repeats these; none of them may keep a bot awake
  for (const t of [10, 20, 30, 40, 50, 59]) { d.send({ type: "phase", phase: "idle" }, t); d.send({ type: "offline", value: false }, t); d.send({ type: "waiting-clear" }, t); d.send({ type: "unread", value: false }, t); }
  assert.equal(d.read(T.SLEEP_AFTER + 0.1).state, "sleep", "asleep 60 s after the last real activity");
  d.send({ type: "hold" }, 70); // found waiting while asleep: the pose shows (it is work), but that is not the reader doing something
  assert.equal(d.read(70 + T.DWELL + 0.1).waitingForUser, true);
});

test("reduced motion: no beats. A finished turn never winks, a failed one keeps its still '!' until the next turn, and there is no dwell floor", () => {
  const d = createDirector({ now: 0, reducedMotion: true });
  d.send({ type: "turn-start" }, 1);
  assert.equal(d.read(1.1).state, "orbit");
  d.send({ type: "turn-end", outcome: "done" }, 1.2); // a turn shorter than the engine's morph floor: the still frame must not be stuck on the old pose
  for (let t = 1.2; t < 10; t += 0.1) assert.equal(d.read(t).state, "idle", `t=${t}`);
  d.send({ type: "turn-start" }, 20);
  assert.equal(d.read(20.1).state, "orbit");
  d.send({ type: "turn-end", outcome: "error" }, 20.2);
  assert.equal(d.read(20.3).state, "alert");
  assert.equal(d.read(3000).state, "alert", "the failure frame stays while the error bar does");
  d.send({ type: "turn-start" }, 4000);
  assert.equal(d.read(4000.1).state, "orbit");
  d.send({ type: "turn-end", outcome: "cancel" }, 4001);
  assert.equal(d.read(4001.1).state, "idle");
  // with motion the same turn still gets its beats and its floor (unchanged)
  const m = createDirector({ now: 0 });
  m.send({ type: "turn-start", quiet: true }, 1); m.read(1.1);
  m.send({ type: "turn-end", outcome: "error" }, 1.2);
  assert.equal(m.read(1.3).state, "orbit", "the dwell floor holds the old body for a moment");
  assert.equal(m.read(1.3 + T.DWELL).state, "alert");
  assert.equal(m.read(1.2 + T.ERROR + 0.7).state, "idle");
});

// ---- A2: the aura's side of the director --------------------------------------------------------------------------------------------------
test("the tool gaze goes to where the aura is (A2): speed lines left, page lines right, the ticker below, the rest follow the moving point", () => {
  const gazeOf = variant => {
    const d = createDirector({ now: 0, persona: { archetype: "tracker", auraVariant: variant } });
    d.send({ type: "turn-start", quiet: true }, 0); d.send({ type: "phase", phase: "tool" }, 0.1);
    return d.read(1).gaze;
  };
  assert.equal(gazeOf("speed-lines"), "side-left");
  assert.equal(gazeOf("page-lines"), "side");
  assert.equal(gazeOf("ticker"), "below");
  for (const variant of ["ticks", "halo", "reticle", "orbit-dots"]) assert.equal(gazeOf(variant), "sweep", variant);
});

test("the view says how the last turn ended and how long ago, until the next turn starts (A2: the aura plays its own end beat)", () => {
  const d = createDirector({ now: 0 });
  assert.deepEqual([d.read(0.1).outcome, d.read(0.1).outcomeAge], [null, null]);
  d.send({ type: "turn-start" }, 1); assert.equal(d.read(1.1).outcome, null);
  d.send({ type: "turn-end", outcome: "partial" }, 4);
  const v = d.read(5); // the nod (0.6 s) is long over, the outcome is still known
  assert.equal(v.outcome, "partial"); assert.ok(Math.abs(v.outcomeAge - 1) < 1e-9); assert.equal(v.pose, "idle");
  d.send({ type: "turn-start" }, 9); assert.equal(d.read(9.1).outcome, null);
  d.send({ type: "turn-end", outcome: "error" }, 12); assert.equal(d.read(12.1).outcome, "error");
  const r = createDirector({ now: 0, reducedMotion: true });
  r.send({ type: "turn-start" }, 1); r.send({ type: "turn-end", outcome: "done" }, 2);
  assert.equal(r.read(30).outcome, "done", "reduced motion keeps it too: the still frame decides how long to show the closed shape");
});
