import test from "node:test";
import assert from "node:assert/strict";
import { createLineStore, lineKey, loadDraft, saveDraft } from "../src/chat-lines.mjs";

const memory = () => { const m = new Map(); return { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) }; };

test("lineKey names bot, conversation and local lines", () => {
  assert.equal(lineKey({ id: "b1" }, "c1"), "bot:b1");
  assert.equal(lineKey(null, "c1"), "conv:c1");
  assert.equal(lineKey(null, null), "local");
});

test("草稿切换后还在", () => {
  const storage = memory(), store = createLineStore(), A = "bot:a", B = "bot:b";
  store.setActive(A); saveDraft(A, "未发完的问题", storage);
  store.setActive(B); saveDraft(B, "", storage);
  store.setActive(A);
  assert.equal(loadDraft(A, storage), "未发完的问题");
  assert.equal(loadDraft(B, storage), "");
  saveDraft(A, "", storage);
  assert.equal(storage.getItem("market-evidence-agent:draft:bot:a:v1"), null);
});

test("切换不中断", () => {
  const store = createLineStore(), A = "bot:a", B = "bot:b", controller = new AbortController();
  store.setActive(A); store.get(A).lifecycle.begin(controller); store.update(A, { state: "sending" });
  store.setActive(B);
  assert.equal(controller.signal.aborted, false);
  assert.deepEqual(store.running(), [A]);
});

test("同线再发才中断", () => {
  const store = createLineStore(), A = "bot:a", first = new AbortController(), second = new AbortController();
  store.get(A).lifecycle.begin(first);
  store.get(A).lifecycle.begin(second);
  assert.equal(first.signal.aborted, true);
  assert.equal(second.signal.aborted, false);
});

test("后台完成打标记", () => {
  const store = createLineStore(), A = "bot:a", B = "bot:b";
  store.setActive(A); store.update(A, { state: "sending" });
  store.setActive(B);
  store.update(A, { state: "ready" });
  assert.deepEqual(store.unseen(), [A]);
  store.markSeen(A);
  assert.deepEqual(store.unseen(), []);
  store.update(B, { state: "sending" }); store.update(B, { state: "ready" });
  assert.deepEqual(store.unseen(), [], "the viewed line is never marked");
});

test("存储报错不影响使用", () => {
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("full"); }, removeItem() { throw new Error("denied"); } };
  assert.equal(loadDraft("bot:a", broken), "");
  assert.doesNotThrow(() => saveDraft("bot:a", "x", broken));
  assert.doesNotThrow(() => saveDraft("bot:a", "", broken));
});
