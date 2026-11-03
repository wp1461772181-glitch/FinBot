import assert from "node:assert/strict";
import test from "node:test";
import { createLineStore } from "../src/chat-lines.mjs";
import { mergeNewTurns, planTailSync, pollDelay } from "../src/chat-sync.mjs";

const u = (turn_id, content = `q-${turn_id}`) => ({ role: "user", content, turn_id });
const a = (turn_id, content = `a-${turn_id}`) => ({ role: "assistant", content, turn_id });
const turn = id => [u(id), a(id)];

test("a turn written from outside is appended after the known ones", () => {
  const local = [...turn("t1"), ...turn("t2")];
  const { messages, added } = mergeNewTurns(local, [...turn("t1"), ...turn("t2"), ...turn("t3")]);
  assert.equal(added, 1);
  assert.deepEqual(messages.map(m => m.turn_id), ["t1", "t1", "t2", "t2", "t3", "t3"]);
  assert.equal(messages[0], local[0], "existing message objects are reused, so nothing re-renders");
});

test("nothing new: the same array comes back", () => {
  const local = [...turn("t1"), ...turn("t2")];
  const result = mergeNewTurns(local, [...turn("t1"), ...turn("t2")]);
  assert.equal(result.messages, local);
  assert.equal(result.added, 0);
});

test("a turn streamed in this tab is not duplicated when the server returns it (local user message has no turn_id)", () => {
  const local = [...turn("t1"), { role: "user", content: "hello" }, a("t2", "streamed answer")];
  const result = mergeNewTurns(local, [...turn("t1"), u("t2", "hello"), a("t2", "saved answer")]);
  assert.equal(result.messages, local);
  assert.equal(result.added, 0);
});

test("a local user message still waiting for its answer is replaced by the saved turn, not repeated", () => {
  const local = [...turn("t1"), { role: "user", content: "hello" }];
  const { messages, added } = mergeNewTurns(local, [...turn("t1"), u("t2", "hello"), a("t2")]);
  assert.equal(added, 1);
  assert.deepEqual(messages.map(m => `${m.role}:${m.turn_id ?? "-"}`), ["user:t1", "assistant:t1", "user:t2", "assistant:t2"]);
});

test("several new turns keep the server order; tool rows are dropped", () => {
  const { messages } = mergeNewTurns(turn("t1"), [...turn("t1"), u("t2"), { role: "tool", content: "{}", turn_id: "t2" }, a("t2"), a("push-1", "reminder")]);
  assert.deepEqual(messages.map(m => m.turn_id), ["t1", "t1", "t2", "t2", "push-1"]);
});

test("an assistant-only turn (reminder / push) is merged", () => {
  const { messages, added } = mergeNewTurns(turn("t1"), [...turn("t1"), a("r1", "提醒")]);
  assert.equal(added, 1);
  assert.equal(messages.at(-1).content, "提醒");
});

test("no overlap with the fetched window: leave the transcript alone", () => {
  const local = turn("t1");
  const result = mergeNewTurns(local, [...turn("t8"), ...turn("t9")]);
  assert.equal(result.messages, local);
  assert.equal(result.gap, true);
});

test("an empty transcript takes the whole window", () => {
  assert.equal(mergeNewTurns([], [...turn("t1")]).added, 1);
});

test("planTailSync: never merges into a streaming, testing or restoring line", () => {
  const tail = [...turn("t1"), ...turn("t2")];
  for (const patch of [{ state: "sending" }, { state: "testing" }, { state: "restoring" }, { restoring: true }]) {
    const store = createLineStore();
    store.update("bot:1", { conversationId: "c1", messages: turn("t1"), ...patch });
    assert.equal(planTailSync(store.get("bot:1"), tail, "c1"), null, JSON.stringify(patch));
  }
});

test("planTailSync: ignores a reply for another conversation", () => {
  const store = createLineStore();
  store.update("bot:1", { conversationId: "c1", messages: turn("t1") });
  assert.equal(planTailSync(store.get("bot:1"), [...turn("t1"), ...turn("t2")], "c2"), null);
});

test("merging a new turn leaves the unsent draft and the status alone", () => {
  const store = createLineStore();
  store.update("bot:1", { conversationId: "c1", messages: turn("t1"), draft: "half-typed question", state: "ready", status: "ok" });
  const plan = planTailSync(store.get("bot:1"), [...turn("t1"), ...turn("t2")], "c1");
  assert.equal(plan.added, 1);
  store.update("bot:1", { messages: plan.messages });
  const line = store.get("bot:1");
  assert.equal(line.draft, "half-typed question");
  assert.equal(line.state, "ready");
  assert.equal(line.status, "ok");
  assert.equal(line.messages.length, 4);
});

test("pollDelay: 4 s while visible, slower when hidden, none for a stopped poller", () => {
  assert.equal(pollDelay({ hidden: false }), 4000);
  assert.ok(pollDelay({ hidden: true }) >= 30000);
  assert.equal(pollDelay({ hidden: false, failures: 2 }), 16000);
  assert.ok(pollDelay({ hidden: false, failures: 20 }) <= 60000);
});
