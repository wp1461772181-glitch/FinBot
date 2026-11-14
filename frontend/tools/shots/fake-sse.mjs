// A chat stream a check feeds by hand.  The fake API (mock-api.mjs) answers a request whole, so it cannot hold a stream
// half-open; a check that needs "some text arrived, the rest has not" installs this in the page instead.
//
// `handFed(page)` wraps window.fetch (the app calls the global at request time): a POST to .../agent-chat/stream whose
// message holds HAND_MARKER gets a ReadableStream response that stays open until the check pushes events or closes it.
// Every other request goes to the real fetch (and so to the fake API).  Aborting the request errors the stream with an
// AbortError, the way the browser does.  Nothing here is part of the app or the build.
import { HAND_MARKER } from "./fixtures/ids.mjs";

export async function handFed(page) {
  await page.evaluate((marker) => {
    if (window.__hand) return;
    const realFetch = window.fetch.bind(window);
    const encoder = new TextEncoder();
    const streams = [];   // one entry per hand-fed request: { body, controller, closed }
    window.__hand = { streams };
    window.fetch = (input, init) => {
      const url = new URL(typeof input === "string" ? input : input.url, location.href);
      if (!/\/agent-chat\/stream$/.test(url.pathname) || (init?.method ?? "GET").toUpperCase() !== "POST") return realFetch(input, init);
      let body = null;
      try { body = JSON.parse(String(init?.body ?? "")); } catch { /* not ours */ }
      if (!body || !String(body.message ?? "").includes(marker)) return realFetch(input, init);
      const entry = { body, controller: null, closed: false, aborted: false };
      streams.push(entry);
      const stream = new ReadableStream({ start(controller) { entry.controller = controller; } });
      init?.signal?.addEventListener("abort", () => {
        entry.aborted = true;
        if (entry.closed) return;
        entry.closed = true;
        try { entry.controller.error(new DOMException("The operation was aborted.", "AbortError")); } catch { /* already closed */ }
      });
      return Promise.resolve(new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } }));
    };
    window.__hand.push = (index, event, data) => {
      const entry = streams[index];
      if (!entry || entry.closed) throw new Error(`hand-fed stream ${index} is not open`);
      entry.controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
    };
    window.__hand.close = (index) => { const entry = streams[index]; if (entry && !entry.closed) { entry.closed = true; entry.controller.close(); } };
  }, HAND_MARKER);
  return {
    /** Wait until the app has opened the n-th hand-fed request; resolves to its JSON body. */
    opened: async (index = 0) => { await page.waitForFunction((i) => Boolean(window.__hand?.streams[i]?.controller), index, { timeout: 10000 }); return page.evaluate((i) => window.__hand.streams[i].body, index); },
    push: (index, event, data) => page.evaluate(([i, e, d]) => window.__hand.push(i, e, d), [index, event, data]),
    close: (index) => page.evaluate((i) => window.__hand.close(i), index),
    aborted: (index) => page.evaluate((i) => Boolean(window.__hand.streams[i]?.aborted), index),
  };
}
