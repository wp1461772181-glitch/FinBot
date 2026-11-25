import test from "node:test";
import assert from "node:assert/strict";
import { addUser, patchByKey, removeByKey, upsertAnswer, replyEntries, replyQuote, deliveries, awaitingAnswer, createStreamSet, queuedText, moveMerged, withdrawAnswer } from "../src/chat-interject.mjs";
import { isActiveClarification } from "../src/chat-clarification.mjs";

const user = (key, content, extra = {}) => ({ role: "user", content, client_key: key, ...extra });
const answer = (key, userKey, extra = {}) => ({ role: "assistant", content: "答", client_key: key, user_key: userKey, ...extra });

test("an interjection is added at once with a sending mark; a normal send carries none", () => {
  const first = addUser([], { key: "u1", content: "NVDA 营收", answerKey: "a1" });
  assert.equal(first[0].delivery, undefined);
  assert.equal(first[0].answer_key, "a1");
  const second = addUser(first, { key: "u2", content: "顺便比 AMD", interject: true });
  assert.equal(second.length, 2);
  assert.equal(second[1].delivery, "sending");
  assert.equal(first.length, 1, "the input list is not changed");
});

test("patchByKey and removeByKey find a message by its client key", () => {
  const list = [user("u1", "a"), user("u2", "b", { delivery: "sending" })];
  const patched = patchByKey(list, "u2", { delivery: "received", id: "m-2" });
  assert.equal(patched[1].delivery, "received");
  assert.equal(patched[1].id, "m-2");
  assert.equal(patched[0], list[0]);
  assert.deepEqual(removeByKey(patched, "u2").map(m => m.client_key), ["u1"]);
  assert.equal(patchByKey(list, "nope", { delivery: "x" }), list);
});

test("an answer is placed under its own message even when an interjection came after it", () => {
  const list = [user("u1", "NVDA"), user("u2", "AMD", { delivery: "received" })];
  const placed = upsertAnswer(list, "u1", answer("a1", "u1", { content: "" }));
  assert.deepEqual(placed.map(m => m.client_key), ["u1", "a1", "u2"]);
  const updated = upsertAnswer(placed, "u1", answer("a1", "u1", { content: "更新" }));
  assert.equal(updated.length, 3);
  assert.equal(updated[1].content, "更新");
});

test("two answers in progress at once each keep their place", () => {
  let list = [user("u1", "NVDA"), user("u2", "记一下 TSLA", { delivery: "separate", answer_key: "a2" })];
  list = upsertAnswer(list, "u2", answer("a2", "u2", { live: true }));
  list = upsertAnswer(list, "u1", answer("a1", "u1", { live: true }));
  assert.deepEqual(list.map(m => m.client_key), ["u1", "a1", "u2", "a2"]);
  list = upsertAnswer(list, "u1", answer("a1", "u1", { live: true, content: "更多" }));
  assert.deepEqual(list.map(m => m.client_key), ["u1", "a1", "u2", "a2"]);
});

test("a live answer with a merged message answers both; one directly below its message has no quote", () => {
  const list = [user("u1", "NVDA 营收"), answer("a1", "u1", { turn_id: "T1" }), user("u2", "顺便比 AMD", { delivery: "merged", into_turn: "T1" })];
  assert.deepEqual(replyEntries(list, 1).map(e => e.text), ["NVDA 营收", "顺便比 AMD"]);
  assert.equal(replyQuote(list, 1), "NVDA 营收 / 顺便比 AMD");
  const plain = [user("u1", "NVDA"), answer("a1", "u1", { turn_id: "T1" })];
  assert.equal(replyQuote(plain, 1), null);
});

test("an answer that is not directly below its message quotes it (stored order after a reload)", () => {
  const list = [
    { role: "user", content: "NVDA 营收", id: "m1", turn_id: "T1" },
    { role: "user", content: "记一下 TSLA", id: "m2", turn_id: "T2" },
    { role: "assistant", content: "A", turn_id: "T1", reply_to: [{ id: "m1", text: "NVDA 营收" }] },
    { role: "assistant", content: "B", turn_id: "T2", reply_to: [{ id: "m2", text: "记一下 TSLA" }] },
  ];
  assert.equal(replyQuote(list, 2), "NVDA 营收");
  assert.equal(replyQuote(list, 3), "记一下 TSLA", "the answer above it is another turn's");
  const adjacent = [list[0], list[2]];
  assert.equal(replyQuote(adjacent, 1), null);
});

test("a stopped answer's live quote names the message that stopped it", () => {
  const list = [user("u1", "写 NVDA 分析"), answer("a1", "u1", { turn_id: "T1", status: "cancelled", stopped_by_message: true }), user("u2", "算了", { delivery: "stopped" })];
  assert.deepEqual(replyEntries(list, 1).map(e => e.text), ["写 NVDA 分析", "算了"]);
});

test("labels: live ones come from the mark, reloaded ones from the answers' reply_to", () => {
  const live = [user("u1", "a"), answer("a1", "u1", { live: true }), user("u2", "b", { delivery: "received" }), user("u3", "c", { delivery: "merged" }), user("u4", "d", { delivery: "stopped" }), user("u5", "e", { delivery: "queued", queue_ahead: 2 })];
  assert.deepEqual(deliveries(live).map(d => d && d.kind), [null, null, "received", "merged", "stopped", "queued"]);
  assert.equal(deliveries(live)[5].ahead, 2);
  const stored = [
    { role: "user", content: "NVDA", id: "m1" }, { role: "user", content: "AMD", id: "m2" },
    { role: "assistant", content: "两个都答了", status: "complete", reply_to: [{ id: "m1", text: "NVDA" }, { id: "m2", text: "AMD" }] },
    { role: "user", content: "写分析", id: "m3" }, { role: "user", content: "算了", id: "m4" },
    { role: "assistant", content: "好的", status: "cancelled", reply_to: [{ id: "m3", text: "写分析" }, { id: "m4", text: "算了" }] },
    { role: "user", content: "独立", id: "m5" }, { role: "assistant", content: "答", status: "complete", reply_to: [{ id: "m5", text: "独立" }] },
  ];
  assert.deepEqual(deliveries(stored).map(d => d && d.kind), [null, "merged", null, null, "stopped", null, null, null]);
});

test("a separate message shows its mark only while its own answer is being written", () => {
  const sep = user("u2", "TSLA", { delivery: "separate", answer_key: "a2" });
  assert.equal(deliveries([sep, answer("a2", "u2", { live: true })])[0].kind, "separate");
  assert.equal(deliveries([sep, answer("a2", "u2", { live: false })])[0], null);
  assert.equal(deliveries([sep])[0].kind, "separate", "its answer has not started");
});

test("awaitingAnswer lists the messages whose own answer has not appeared yet", () => {
  const list = [user("u1", "a", { answer_key: "a1" }), user("u2", "b", { delivery: "received" }), user("u3", "c", { delivery: "separate", answer_key: "a3" })];
  assert.deepEqual([...awaitingAnswer(list, true)], [0, 2]);
  assert.deepEqual([...awaitingAnswer(upsertAnswer(list, "u1", answer("a1", "u1")), true)], [3]);
  assert.deepEqual([...awaitingAnswer(list, false)], []);
});

test("the stop button names the newest turn that is writing an answer", () => {
  const set = createStreamSet();
  const a = { key: "a", answer: true, dead: false }, b = { key: "b", answer: false, dead: false };
  set.add("bot:1", a); set.add("bot:1", b);
  assert.equal(set.stopTarget("bot:1"), a, "an interjection that has no answer is not the target");
  b.answer = true;
  assert.equal(set.stopTarget("bot:1"), b);
  b.dead = true;
  assert.equal(set.stopTarget("bot:1"), a);
  assert.equal(set.count("bot:1"), 2);
  set.remove("bot:1", a); set.remove("bot:1", b);
  assert.equal(set.count("bot:1"), 0);
  assert.equal(set.stopTarget("bot:1"), null);
});

test("killOthers marks every stream of a line but the main one dead", () => {
  const set = createStreamSet(), aborted = [];
  const main = { key: "m", main: true, dead: false, controller: { abort: () => aborted.push("m") } }, extra = { key: "x", main: false, dead: false, controller: { abort: () => aborted.push("x") } };
  set.add("l", main); set.add("l", extra);
  set.killExtras("l");
  assert.deepEqual(aborted, ["x"]);
  assert.equal(extra.dead, true);
  assert.equal(main.dead, false);
});

test("the queue sentence", () => {
  assert.equal(queuedText(3, "zh-CN"), "排队中（前面 3 件）");
  assert.equal(queuedText(1, "en-US"), "Queued (1 ahead)");
});

test("a merged message is inserted above the answer it merged into, so a card on that answer stays answerable", () => {
  let list = [user("u1", "买 10 股 NVDA"), answer("a1", "u1", { turn_id: "T1", status: "waiting_for_input", clarification: { request_id: "r" } }), user("u2", "不对，是 20 股", { delivery: "merged", into_turn: "T1" })];
  assert.equal(isActiveClarification(list, 1, false), false, "the old order: the card is not last");
  list = moveMerged(list, "u2", { intoTurn: "T1" });
  assert.deepEqual(list.map(m => m.client_key), ["u1", "u2", "a1"]);
  assert.equal(isActiveClarification(list, 2, false), true);
});

test("a merge that arrives before the answer exists sits under its target message, and the answer then goes below it", () => {
  let list = [user("u1", "NVDA"), user("u2", "AMD", { delivery: "merged", into_turn: "T1" })];
  list = moveMerged(list, "u2", { intoTurn: "T1", targetUserKey: "u1" });
  list = upsertAnswer(list, "u1", answer("a1", "u1", { turn_id: "T1" }));
  assert.deepEqual(list.map(m => m.client_key), ["u1", "u2", "a1"]);
  const two = upsertAnswer([user("u1", "NVDA"), user("u2", "AMD", { delivery: "merged", into_turn: "T1" }), user("u3", "TSLA", { delivery: "merged", into_turn: "T1" })], "u1", answer("a1", "u1", { turn_id: "T1" }));
  assert.deepEqual(two.map(m => m.client_key), ["u1", "u2", "u3", "a1"]);
  assert.equal(moveMerged(list, "nope", { intoTurn: "T1" }), list);
});

test("withdrawing an answer removes it and the message stops waiting for it", () => {
  const list = [user("u1", "a", { answer_key: "a1" }), answer("a1", "u1")];
  const out = withdrawAnswer(list, "u1", "a1");
  assert.equal(out.length, 1);
  assert.equal(out[0].answer_key, undefined);
  assert.deepEqual([...awaitingAnswer(out, true)], []);
});

test("a queued message that never started says so; a stopped-status answer marks its stopper", () => {
  assert.equal(deliveries([user("u1", "a", { delivery: "unstarted" })])[0].kind, "unstarted");
  const stored = [{ role: "user", id: "m1", content: "x" }, { role: "user", id: "m2", content: "算了" }, { role: "assistant", status: "stopped", reply_to: [{ id: "m1", text: "x" }, { id: "m2", text: "算了" }] }];
  assert.equal(deliveries(stored)[1].kind, "stopped");
});
