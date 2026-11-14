// Is the backend reachable?  (design 4.0, 全局不可达)  Pure: no React, no window; the browser is passed in.
//
// There is no probe: the answer comes from the requests the app makes anyway.  A request that fails the way an
// unreachable server fails (the network error fetch raises, or a gateway answer from a proxy with no backend behind it)
// lights the flag; any answer that came from the backend, whatever its status, puts it out.  An application error
// (a 4xx, a 500 with a JSON body) means the backend is there, so it is never "offline".

const GATEWAY = new Set([502, 503, 504]);

/**
 * What one finished request says about reachability: "down", "up", or "ignore" (the request says nothing: it was cancelled).
 * A 502/503/504 is "down" only when it is not the application's own JSON error: a proxy's page is HTML or plain text,
 * while the backend's own capacity errors carry a JSON body.
 */
export function classifyOutcome({ error, status, contentType } = {}) {
  if (error) {
    if (error?.name === "AbortError") return "ignore";
    return error instanceof TypeError ? "down" : "ignore";
  }
  if (typeof status !== "number") return "ignore";
  if (GATEWAY.has(status) && !/json/i.test(String(contentType ?? ""))) return "down";
  return "up";
}

/** A request is replayable when it only reads. */
function isRead(input, init) {
  const method = String(init?.method ?? (typeof input === "object" && input && "method" in input ? input.method : "GET")).toUpperCase();
  return method === "GET" && !init?.signal?.aborted;
}

/** The flag and its listeners.  The snapshot object changes only when the flag does, so it can feed useSyncExternalStore. */
export function createConnectivity({ now = () => Date.now() } = {}) {
  let snapshot = { down: false, since: null, reason: "" };
  let lastFailedRead = null;
  const listeners = new Set();
  const set = (next) => { snapshot = next; for (const listener of [...listeners]) listener(); };
  return {
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    /** Feed one request's outcome (see classifyOutcome); `replay` is what to run again to check the backend is back. */
    report(outcome, { reason = "network", replay = null } = {}) {
      if (outcome === "down") {
        if (replay) lastFailedRead = replay;
        if (!snapshot.down) set({ down: true, since: now(), reason });
      } else if (outcome === "up") {
        lastFailedRead = null;
        if (snapshot.down) set({ down: false, since: null, reason: "" });
      }
    },
    /** The last read that failed, if the failure was a read. */
    lastFailedRead: () => lastFailedRead,
    /**
     * 重试: run the last failed read again (its outcome is reported like any request's).  With none to run (the failure was a
     * write, or the browser went offline), the flag is put out on trust: the next request lights it again if it is still down.
     */
    async retry(run) {
      if (lastFailedRead && run) { try { await run(lastFailedRead); } catch { /* reported by the watcher */ } return; }
      if (snapshot.down) set({ down: false, since: null, reason: "" });
    },
  };
}

/**
 * Watch `host.fetch`: wrap it so every API request reports to `store`, and follow the browser's own online/offline events.
 * The wrapper passes the request through untouched (same arguments, same result or rejection).  `isApi(url)` picks the
 * requests that speak for the backend (fonts and the like do not).  Returns the function that undoes it.
 */
export function watchConnectivity(store, { host = globalThis, isApi = () => true } = {}) {
  const original = host.fetch;
  if (typeof original !== "function") return () => {};
  const urlOf = (input) => typeof input === "string" ? input : input instanceof URL ? input.href : input?.url ?? "";
  const wrapped = async function (input, init) {
    const url = urlOf(input);
    if (!isApi(url)) return original.call(host, input, init);
    const replay = isRead(input, init) ? { input, init } : null;
    try {
      const response = await original.call(host, input, init);
      store.report(classifyOutcome({ status: response.status, contentType: response.headers?.get?.("content-type") }), { reason: `http ${response.status}`, replay });
      return response;
    } catch (error) {
      store.report(classifyOutcome({ error }), { reason: "network", replay });
      throw error;
    }
  };
  host.fetch = wrapped;
  const goOffline = () => store.report("down", { reason: "offline" });
  const goOnline = () => { void store.retry((request) => host.fetch(request.input, request.init)); };
  host.addEventListener?.("offline", goOffline);
  host.addEventListener?.("online", goOnline);
  return () => {
    if (host.fetch === wrapped) host.fetch = original;
    host.removeEventListener?.("offline", goOffline);
    host.removeEventListener?.("online", goOnline);
  };
}
