import assert from "node:assert/strict";
import test from "node:test";
import {
  FAILED_TEXT, REASON_PLACEHOLDER, THUMBS, asksReason, feedbackRequest, uploadBody, cleanReason, feedbackBody, forgetLocal, localKey, nextVerdict, readLocal, serverVerdict, toggleLocal, uploadFor,
} from "../src/answer-feedback.mjs";

function memoryStore(entries = {}) {
  const map = new Map(Object.entries(entries));
  return { getItem: (key) => (map.has(key) ? map.get(key) : null), setItem: (key, value) => map.set(key, String(value)), removeItem: (key) => map.delete(key), map };
}
const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };

test("the browser's old notes read as verdicts under the old key; a blocked storage is no verdict", () => {
  const store = memoryStore({ [localKey("t1")]: "up", [localKey("t2")]: "down", [localKey("t3")]: "junk" });
  assert.equal(localKey("t1"), "market-evidence-agent:feedback:t1");
  assert.deepEqual(["t1", "t2", "t3", "t4"].map((turn) => readLocal(store, turn)), ["good", "bad", null, null]);
  assert.equal(readLocal(broken, "t1"), null);
  assert.equal(readLocal(store, ""), null);
});

test("a press: the same thumb takes the verdict back, the other replaces it; only a new 不好 asks why", () => {
  assert.equal(nextVerdict(null, "good"), "good");
  assert.equal(nextVerdict("good", "good"), null);
  assert.equal(nextVerdict("good", "bad"), "bad");
  assert.equal(asksReason(null, "bad"), true);
  assert.equal(asksReason("good", "bad"), true);
  assert.equal(asksReason("bad", "bad"), false, "taking 不好 back does not ask");
  assert.equal(asksReason(null, "good"), false);
});

test("the body sent: a reason only with 不好, one line, at most 200 characters", () => {
  assert.deepEqual(feedbackBody("good", "很好"), { verdict: "good" });
  assert.deepEqual(feedbackBody("bad", "  数据\n太旧了 "), { verdict: "bad", reason: "数据 太旧了" });
  assert.deepEqual(feedbackBody("bad", "   "), { verdict: "bad" });
  assert.equal(cleanReason("x".repeat(250)).length, 200);
  assert.equal(cleanReason(null), null);
});

test("the server's verdict wins; an old note is sent once only for a stored answer the server has none on", () => {
  const store = memoryStore({ [localKey("t1")]: "down" });
  const stored = { role: "assistant", id: "m1", turn_id: "t1" };
  assert.equal(serverVerdict({ feedback: { verdict: "good" } }), "good");
  assert.equal(serverVerdict({ feedback: { verdict: "meh" } }), null);
  assert.equal(uploadFor(stored, store), "bad");
  assert.equal(uploadFor({ ...stored, feedback: { verdict: "good" } }, store), null, "the server has one: nothing is sent");
  assert.equal(uploadFor({ ...stored, id: undefined }, store), null, "not stored yet: it waits");
  assert.equal(uploadFor({ ...stored, role: "user" }, store), null);
  assert.equal(uploadFor({ ...stored, turn_id: "t9" }, store), null, "no note here");
  forgetLocal(store, "t1");
  assert.equal(store.map.size, 0);
  forgetLocal(broken, "t1");          // never throws
});

test("a guest's thumbs stay a note in this browser, as before", () => {
  const store = memoryStore();
  assert.equal(toggleLocal(store, "t1", "good"), "good");
  assert.equal(store.getItem(localKey("t1")), "up");
  assert.equal(toggleLocal(store, "t1", "bad"), "bad");
  assert.equal(store.getItem(localKey("t1")), "down");
  assert.equal(toggleLocal(store, "t1", "bad"), null);
  assert.equal(store.getItem(localKey("t1")), null);
  assert.equal(toggleLocal(broken, "t1", "good"), "good", "a blocked storage does not break the press");
});

test("the words are in both locales", async () => {
  const { readFileSync } = await import("node:fs");
  const zh = JSON.parse(readFileSync(new URL("../src/locales/zh-CN.json", import.meta.url)));
  const en = JSON.parse(readFileSync(new URL("../src/locales/en-US.json", import.meta.url)));
  for (const phrase of [REASON_PLACEHOLDER, FAILED_TEXT, ...THUMBS.map((thumb) => thumb.label), "发送", "跳过"]) {
    assert.ok(zh.includes(phrase), phrase);
    assert.ok(typeof en[phrase] === "string" && en[phrase], phrase);
  }
});

test("the requests: PUT with the body and the session, DELETE with none; ids are escaped; the upload keeps a verdict the server has", () => {
  const put = feedbackRequest("https://api.example/agent-chat/", "c 1", "t/2", "PUT", { verdict: "bad", reason: "太旧" }, "cred");
  assert.equal(put.url, "https://api.example/agent-chat/conversations/c%201/turns/t%2F2/feedback");
  assert.deepEqual(put.init, { method: "PUT", cache: "no-store", headers: { Accept: "application/json", "X-Chat-Session": "cred", "Content-Type": "application/json" },
    body: JSON.stringify({ verdict: "bad", reason: "太旧" }) });
  const del = feedbackRequest("https://api.example/agent-chat/", "c1", "t2", "DELETE", null, "cred");
  assert.deepEqual(del.init, { method: "DELETE", cache: "no-store", headers: { Accept: "application/json", "X-Chat-Session": "cred" } });
  assert.equal("body" in del.init, false);
  assert.deepEqual(uploadBody("good"), { verdict: "good", if_absent: true });
});
