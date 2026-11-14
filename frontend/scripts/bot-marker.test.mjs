import assert from "node:assert/strict";
import test from "node:test";
import { botMarker, countLabel, isWaiting } from "../src/bot-marker.mjs";

test("a quiet bot shows nothing", () => {
  assert.deepEqual(botMarker({}), { kind: "none", ring: false, dot: false, word: null, count: 0 });
  assert.deepEqual(botMarker(), { kind: "none", ring: false, dot: false, word: null, count: 0 });
});

test("each state has its own mark: ring, dot, number", () => {
  assert.deepEqual(botMarker({ running: true }), { kind: "running", ring: true, dot: false, word: "running", count: 0 });
  assert.deepEqual(botMarker({ waiting: true }), { kind: "waiting", ring: false, dot: true, word: "waiting", count: 0 });
  assert.deepEqual(botMarker({ unread: 3 }), { kind: "unread", ring: false, dot: false, word: null, count: 3 });
});

test("precedence: answering beats waiting beats unread, and the number still shows", () => {
  const all = botMarker({ running: true, waiting: true, unread: 2 });
  assert.equal(all.kind, "running"); assert.equal(all.ring, true); assert.equal(all.dot, false); assert.equal(all.word, "running"); assert.equal(all.count, 2);
  const waitingAndUnread = botMarker({ waiting: true, unread: 5 });
  assert.equal(waitingAndUnread.kind, "waiting"); assert.equal(waitingAndUnread.dot, true); assert.equal(waitingAndUnread.count, 5);
});

test("the open line's own bot is being read: no number", () => {
  assert.equal(botMarker({ unread: 4, active: true }).count, 0);
  assert.equal(botMarker({ unread: 4, active: true }).kind, "none");
  assert.equal(botMarker({ running: true, unread: 4, active: true }).ring, true);
});

test("garbage counts are quiet", () => {
  assert.equal(botMarker({ unread: -2 }).count, 0);
  assert.equal(botMarker({ unread: NaN }).count, 0);
  assert.equal(botMarker({ unread: 2.9 }).count, 2);
  assert.equal(countLabel(7), "7");
  assert.equal(countLabel(120), "99+");
});

test("a bot waits for you when the server counts something pending or its line ends on an open card", () => {
  assert.equal(isWaiting({ id: "a", pending: 1 }, []), true);
  assert.equal(isWaiting({ id: "a", pending: 0 }, ["bot:a"]), true);
  assert.equal(isWaiting({ id: "a", pending: 0 }, ["bot:b"]), false);
  assert.equal(isWaiting({ id: "a" }), false);
  assert.equal(isWaiting(null, undefined), false);
});
