import assert from "node:assert/strict";
import test from "node:test";
import { classifyOutcome, createConnectivity, watchConnectivity } from "../src/connectivity.mjs";

test("a network error is down; a cancelled request and other exceptions say nothing", () => {
  assert.equal(classifyOutcome({ error: new TypeError("Failed to fetch") }), "down");
  assert.equal(classifyOutcome({ error: new DOMException("aborted", "AbortError") }), "ignore");
  assert.equal(classifyOutcome({ error: new Error("boom") }), "ignore");
  assert.equal(classifyOutcome({}), "ignore");
});

test("any answer from the backend is up, including its own errors", () => {
  for (const status of [200, 204, 304, 400, 401, 403, 404, 422, 429, 500]) assert.equal(classifyOutcome({ status, contentType: "application/json" }), "up", String(status));
});

test("a gateway answer is down unless it is the application's own JSON error", () => {
  for (const status of [502, 503, 504]) {
    assert.equal(classifyOutcome({ status, contentType: "text/html" }), "down", `${status} html`);
    assert.equal(classifyOutcome({ status, contentType: null }), "down", `${status} none`);
    assert.equal(classifyOutcome({ status, contentType: "application/json; charset=utf-8" }), "up", `${status} json`);
  }
});

test("the flag lights on down, goes out on one success, and the snapshot only changes with the flag", () => {
  let t = 1000;
  const store = createConnectivity({ now: () => t });
  let calls = 0; store.subscribe(() => { calls += 1; });
  const first = store.getSnapshot();
  assert.equal(first.down, false);
  store.report("ignore"); store.report("up");
  assert.equal(store.getSnapshot(), first, "no change, same snapshot");
  store.report("down", { reason: "network" });
  const down = store.getSnapshot();
  assert.deepEqual({ down: down.down, since: down.since, reason: down.reason }, { down: true, since: 1000, reason: "network" });
  t = 2000; store.report("down");
  assert.equal(store.getSnapshot(), down, "a second failure keeps the first snapshot (and its start time)");
  store.report("up");
  assert.equal(store.getSnapshot().down, false);
  assert.equal(calls, 2);
});

test("retry replays the last failed read and its success puts the flag out; with nothing to replay it clears on trust", async () => {
  const store = createConnectivity();
  store.report("down", { replay: { input: "https://api.test/x", init: { method: "GET" } } });
  const ran = [];
  await store.retry(async (request) => { ran.push(request.input); store.report("down"); });
  assert.deepEqual(ran, ["https://api.test/x"]);
  assert.equal(store.getSnapshot().down, true, "still down: the replay failed");
  await store.retry(async () => { store.report("up"); });
  assert.equal(store.getSnapshot().down, false);

  store.report("down", { reason: "offline" });
  assert.equal(store.lastFailedRead(), null);
  await store.retry(async () => { throw new Error("must not run"); });
  assert.equal(store.getSnapshot().down, false);
});

function fakeHost(behaviour) {
  const events = new Map();
  const host = {
    calls: [],
    fetch: async (input, init) => { host.calls.push({ input, init }); return behaviour(input, init); },
    addEventListener(name, fn) { events.set(name, fn); },
    removeEventListener(name) { events.delete(name); },
    emit(name) { events.get(name)?.(); },
  };
  return host;
}
const reply = (status, contentType = "application/json") => ({ status, headers: { get: () => contentType } });

test("the fetch wrapper passes requests through and reports only API requests", async () => {
  const store = createConnectivity();
  let mode = "fail";
  const host = fakeHost(async (input) => { if (mode === "fail") throw new TypeError("Failed to fetch"); return reply(200); });
  const stop = watchConnectivity(store, { host, isApi: (url) => url.startsWith("https://api.test/") });
  await assert.rejects(host.fetch("https://cdn.test/font.woff2"), TypeError);
  assert.equal(store.getSnapshot().down, false, "not an API request");
  await assert.rejects(host.fetch("https://api.test/bots", { method: "GET" }), TypeError);
  assert.equal(store.getSnapshot().down, true);
  assert.equal(store.lastFailedRead().input, "https://api.test/bots");
  mode = "ok";
  const response = await host.fetch("https://api.test/other", { method: "POST", body: "{}" });
  assert.equal(response.status, 200);
  assert.equal(store.getSnapshot().down, false, "one success puts it out");
  stop();
});

test("a failed write is not replayed; retry just clears", async () => {
  const store = createConnectivity();
  const host = fakeHost(async () => { throw new TypeError("Failed to fetch"); });
  const stop = watchConnectivity(store, { host });
  await assert.rejects(host.fetch("https://api.test/save", { method: "PUT", body: "[]" }), TypeError);
  assert.equal(store.getSnapshot().down, true);
  assert.equal(store.lastFailedRead(), null);
  const callsBefore = host.calls.length;
  await store.retry(async () => { throw new Error("no replay for a write"); });
  assert.equal(host.calls.length, callsBefore);
  assert.equal(store.getSnapshot().down, false);
  stop();
});

test("the browser's offline and online events drive the flag; online replays the failed read", async () => {
  const store = createConnectivity();
  let up = false;
  const host = fakeHost(async () => { if (!up) throw new TypeError("x"); return reply(200); });
  const stop = watchConnectivity(store, { host });
  host.emit("offline");
  assert.equal(store.getSnapshot().down, true);
  assert.equal(store.getSnapshot().reason, "offline");
  await assert.rejects(host.fetch("https://api.test/bots"), TypeError);
  up = true; host.emit("online");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(store.getSnapshot().down, false);
  stop();
  assert.equal(typeof host.fetch, "function");
});

test("stopping the watch restores fetch", async () => {
  const store = createConnectivity();
  const host = fakeHost(async () => reply(200));
  const original = host.fetch;
  const stop = watchConnectivity(store, { host });
  assert.notEqual(host.fetch, original);
  stop();
  assert.equal(host.fetch, original);
});
