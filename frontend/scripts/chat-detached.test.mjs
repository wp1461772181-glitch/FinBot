import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import * as D from "../src/chat-detached.mjs";
import { mergeNewTurns, planTailSync } from "../src/chat-sync.mjs";
import { newTurnIds } from "../src/chat-states.mjs";

const user = (content, turn_id) => ({ role: "user", content, ...(turn_id ? { turn_id } : {}) });
const answer = (content, turn_id, status = "complete") => ({ role: "assistant", content, turn_id, status });
const memoryStorage = (initial = {}) => {
  const map = new Map(Object.entries(initial));
  return { map, getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => map.set(k, String(v)), removeItem: (k) => map.delete(k) };
};

// C1 — streamBreak: the four outcomes over every combination the spec lists.
test("C1 streamBreak covers the four outcomes", () => {
  assert.equal(D.streamBreak({ aborted: true, detachable: true, sawTerminal: false, closed: true }), "stopped");
  assert.equal(D.streamBreak({ aborted: true, detachable: false, sawTerminal: false, closed: false }), "stopped");
  assert.equal(D.streamBreak({ aborted: false, detachable: true, sawTerminal: false, closed: true }), "ended");
  assert.equal(D.streamBreak({ aborted: false, detachable: true, sawTerminal: false, closed: false }), "detached");
  assert.equal(D.streamBreak({ aborted: false, detachable: true, sawTerminal: true, closed: false }), "failed");
  assert.equal(D.streamBreak({ aborted: false, detachable: true, sawTerminal: true, closed: true }), "failed");
  assert.equal(D.streamBreak({ aborted: false, detachable: false, sawTerminal: false, closed: true }), "failed");
  assert.equal(D.streamBreak({ aborted: false, detachable: false, sawTerminal: false, closed: false }), "failed");
});

// C2 — the merge of a turn that arrives behind an unanswered question of this page: the question appears once, the answer last.
test("C2 a question sent here is not doubled when its turn arrives", () => {
  const local = [user("a", "t1"), answer("x", "t1"), user("q")];
  const server = [user("a", "t1"), answer("x", "t1"), user("q", "t2"), answer("y", "t2")];
  const merged = mergeNewTurns(local, server).messages;
  assert.equal(merged.filter((m) => m.content === "q").length, 1);
  assert.equal(merged.at(-1).turn_id, "t2");
  assert.equal(merged.at(-1).role, "assistant");
});

// C3 — a busy send restores the list before the send; the question A then appears once, B never does.
test("C3 a busy resend keeps question A once; the old shape duplicates it", () => {
  const before = [user("a", "t1"), answer("x", "t1"), user("A")];
  const server = [user("a", "t1"), answer("x", "t1"), user("A", "t2"), answer("A-answer", "t2")];
  const merged = mergeNewTurns(before, server).messages;
  assert.equal(merged.filter((m) => m.content === "A").length, 1);
  assert.equal(merged.at(-1).turn_id, "t2");
  assert.equal(merged.at(-1).role, "assistant");
  assert.equal(merged.some((m) => m.content === "B"), false);
  // the old shape [t1, A, B, failed] merged with the same server tail: A shows twice (why the list is restored, not kept)
  const old = [user("a", "t1"), answer("x", "t1"), user("A"), user("B"), answer("", undefined, "failed")];
  const oldMerged = mergeNewTurns(old, server).messages;
  assert.equal(oldMerged.filter((m) => m.content === "A").length, 2);
});

// C4 — a half turn (question only) is not merged and does not clear the background; the whole turn later does both.
test("C4 a half turn neither merges nor clears the background", () => {
  const local = [user("a", "t1"), answer("x", "t1"), user("q")];
  const half = [user("a", "t1"), answer("x", "t1"), user("q", "t2")];
  const whole = D.completeTurnsOnly(half);
  assert.equal(whole.some((m) => m.turn_id === "t2"), false);
  assert.equal(planTailSync({ state: "ready", restoring: false, conversationId: "c1", messages: local }, whole, "c1"), null);
  const background = { conversationId: "c1", turnId: "t2", reason: "dropped", at: 0 };
  assert.equal(D.arrivalSplit({ arrived: newTurnIds(local, whole), messages: whole, ownTurnId: "t2", background }).clearBackground, false);
  const done = [...half, answer("y", "t2")];
  const split = D.arrivalSplit({ arrived: newTurnIds(local, done), messages: done, ownTurnId: "t2", background });
  assert.equal(split.clearBackground, true);
  assert.deepEqual(split.away, ["t2"]);
});

// C5 — arrivalSplit: own complete → away; own cancelled or failed → neither; another turn → external; unknown background turn → any arrival clears it.
test("C5 arrivalSplit sorts arrivals and clears the background", () => {
  const bg = { conversationId: "c1", turnId: "t2", reason: "dropped", at: 0 };
  const complete = [user("q", "t2"), answer("y", "t2", "complete")];
  assert.deepEqual(D.arrivalSplit({ arrived: ["t2"], messages: complete, ownTurnId: "t2", background: bg }), { away: ["t2"], external: [], clearBackground: true, ownArrived: true });
  for (const status of ["cancelled", "failed"]) {
    const messages = [user("q", "t2"), answer("", "t2", status)];
    assert.deepEqual(D.arrivalSplit({ arrived: ["t2"], messages, ownTurnId: "t2", background: bg }), { away: [], external: [], clearBackground: true, ownArrived: true });
  }
  const other = [user("z", "t3"), answer("w", "t3")];
  assert.deepEqual(D.arrivalSplit({ arrived: ["t3"], messages: other, ownTurnId: "t2", background: bg }), { away: [], external: ["t3"], clearBackground: false, ownArrived: false });
  const unknown = { conversationId: "c1", turnId: null, reason: "busy", at: 0 };
  assert.equal(D.arrivalSplit({ arrived: ["t3"], messages: other, ownTurnId: null, background: unknown }).clearBackground, true);
  assert.equal(D.arrivalSplit({ arrived: [], messages: [], ownTurnId: null, background: unknown }).clearBackground, false);
});

// C6 — the local note: write, read, drop round-trip; corrupt JSON or wrong field types read as null; a throwing storage never throws.
test("C6 the note round-trips and survives bad storage", () => {
  const store = memoryStorage();
  const rec = { turnId: "t9", question: "q", at: 1700000000000 };
  D.saveDetached(store, "c1", rec);
  assert.deepEqual(D.loadDetached(store, "c1"), rec);
  D.markDetachedGone(store, "c1");
  assert.equal(D.loadDetached(store, "c1").gone, true);
  D.dropDetached(store, "c1");
  assert.equal(D.loadDetached(store, "c1"), null);
  store.setItem(D.detachedKey("c2"), "{not json");
  assert.equal(D.loadDetached(store, "c2"), null);
  store.setItem(D.detachedKey("c3"), JSON.stringify({ turnId: 5, question: "q", at: 1 }));
  assert.equal(D.loadDetached(store, "c3"), null);
  store.setItem(D.detachedKey("c4"), JSON.stringify({ turnId: "t", question: "q", at: "soon" }));
  assert.equal(D.loadDetached(store, "c4"), null);
  const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("full"); }, removeItem() { throw new Error("blocked"); } };
  assert.doesNotThrow(() => D.saveDetached(throwing, "c1", rec));
  assert.equal(D.loadDetached(throwing, "c1"), null);
  assert.doesNotThrow(() => D.dropDetached(throwing, "c1"));
  assert.doesNotThrow(() => D.markDetachedGone(throwing, "c1"));
});

// C7 — resumePlan: none / arrived (failed → not away) / running / expired (the boundary counts as running) / gone.
test("C7 resumePlan covers its five outcomes", () => {
  const now = 1700002000000;
  const marker = { turnId: "t9", question: "q", at: now - 1000 };
  assert.deepEqual(D.resumePlan({ marker: null, messages: [], now }), { kind: "none" });
  assert.deepEqual(D.resumePlan({ marker, messages: [user("q", "t9"), answer("y", "t9", "complete")], now }), { kind: "arrived", turnId: "t9", away: true });
  assert.deepEqual(D.resumePlan({ marker, messages: [user("q", "t9"), answer("", "t9", "failed")], now }), { kind: "arrived", turnId: "t9", away: false });
  assert.deepEqual(D.resumePlan({ marker, messages: [user("q")], now }), { kind: "running", turnId: "t9", question: "q", at: now - 1000 });
  const edge = { turnId: "t9", question: "q", at: now - D.BACKGROUND_WAIT_MS };
  assert.equal(D.resumePlan({ marker: edge, messages: [], now }).kind, "running");
  assert.equal(D.resumePlan({ marker: { ...edge, at: edge.at - 1 }, messages: [], now }).kind, "expired");
  assert.deepEqual(D.resumePlan({ marker: { ...marker, gone: true }, messages: [], now }), { kind: "gone" });
  assert.equal(D.resumePlan({ marker: { ...marker, gone: true }, messages: [user("q", "t9"), answer("y", "t9")], now }).kind, "arrived");
});

// C8 — nextChunk: a watch-off read waits however long; a watch-on silent reader is cancelled exactly once; a read that wins clears the timer.
test("C8 nextChunk waits without a watch, gives up with one, and clears its timer", async () => {
  const slow = { read: () => new Promise((resolve) => setTimeout(() => resolve({ done: false, value: 1 }), 40)), cancel: async () => {} };
  assert.deepEqual(await D.nextChunk(slow, { idleMs: 10, watch: false }), { done: false, value: 1 });
  let cancels = 0;
  const silent = { read: () => new Promise(() => {}), cancel: async () => { cancels += 1; } };
  assert.deepEqual(await D.nextChunk(silent, { idleMs: 20, watch: true }), { idle: true });
  assert.equal(cancels, 1);
  const quick = { read: async () => ({ done: false, value: 2 }), cancel: async () => { cancels += 1; } };
  assert.deepEqual(await D.nextChunk(quick, { idleMs: 30000, watch: true }), { done: false, value: 2 });
  assert.equal(cancels, 1);
});

// C9 — restoredBeforeSend is reference equality: the same list back is no turn; an equal copy is not the same list.
test("C9 restoredBeforeSend reads the reference, not the length", () => {
  const before = [user("a", "t1"), answer("x", "t1"), user("A"), answer("", "t2", "failed")];
  assert.equal(D.restoredBeforeSend(before, before), true);
  assert.equal(D.restoredBeforeSend(before, [...before]), false);
  assert.equal(D.restoredBeforeSend(undefined, before), false);
  assert.equal(D.restoredBeforeSend(null, null), false);
});

// C10 — the copy constraints of §5, per language: Chinese forbids the internal shapes and `turn`; English forbids the shapes and detach/409 only.
test("C10 the thirteen strings keep the structural constraints", async () => {
  const zh = JSON.parse(await readFile(new URL("../src/locales/zh-CN.json", import.meta.url), "utf8"));
  const en = JSON.parse(await readFile(new URL("../src/locales/en-US.json", import.meta.url), "utf8"));
  const Z = {
    Z1: "连接断开了：这一轮仍在服务器上继续，完成后会自动出现在这里。",
    Z2: "没能通知服务器停止：这一轮可能仍在后台继续，完成后会出现在对话里。",
    Z3: "上一条消息还在回答中（可能在别的页面、Telegram 或后台），等它答完再发。",
    Z4: "上次离开时这一轮还没答完，它应该仍在服务器上继续，完成后会自动出现在这里。",
    Z5: "停止后台回答",
    Z6: "已请求停止后台回答。",
    Z7: "后台那一轮已经结束，结果会自动出现在这里。",
    Z8: "没有能从这里停止的回答：它可能刚好答完（现在可以再发），也可能来自 Telegram 或未刷新的旧页面（只能等它答完）。",
    Z9: "没能连上服务器，稍后再试。",
    Z10: "这一轮在停止前已经答完，结果会自动出现在这里。",
    Z11: "这一轮在服务器上结束了，但这里没有收到回答；已保存的结果会自动出现在对话里。",
    Z12: "后台那一轮一直没有结果出现，可能已被中断；需要的话可以再发一次。",
    Z13: "离开期间已完成",
  };
  for (const [key, text] of Object.entries(Z)) {
    assert.ok(zh.includes(text), `${key} is in zh-CN`);
    assert.ok(en[text]?.trim(), `${key} has an English line`);
    const english = en[text];
    // constraint 1: no internal-code shape anywhere; zh also forbids detach/409/turn; en allows the word turn
    assert.equal(/[a-z]+_[a-z_]+/.test(text), false, `${key} zh has a code shape`);
    assert.equal(/detach|409/.test(text) || /turn/.test(text), false, `${key} zh has an internal word`);
    assert.equal(/[a-z]+_[a-z_]+/.test(english), false, `${key} en has a code shape`);
    assert.equal(/detach|409/.test(english), false, `${key} en has an internal word`);
  }
  // constraint 2: Z1, Z2, Z4 never say 「已停止」; Z6 says 「已请求停止」 only
  for (const key of ["Z1", "Z2", "Z4", "Z6"]) assert.equal(Z[key].includes("已停止"), false, `${key} says stopped`);
  assert.ok(Z.Z6.includes("已请求停止"));
  // constraint 3: Z2 and Z12 keep 「可能」; Z4 says 「应该」
  assert.ok(Z.Z2.includes("可能") && Z.Z12.includes("可能"));
  assert.ok(Z.Z4.includes("应该"));
  // constraint 4: Z8 promises no stop of Telegram or an older page
  assert.equal(/能停|可以停/.test(Z.Z8), false);
  // constraint 5: Z3 promises no queue and no automatic resend
  assert.equal(/排队|自动重发|自动发送/.test(Z.Z3), false);
});
