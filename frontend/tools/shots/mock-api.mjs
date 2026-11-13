// Fake backend for the screenshot / smoke tools.
//
// The built frontend talks to `https://api.example.test` (the VITE_API_BASE_URL that `fe-check.sh build` bakes in).
// Every request to that origin is intercepted here and answered from ./fixtures by "method + path"; every other
// external request is aborted.  A request no fixture answers gets 404 {"detail":"shots: no fixture"} and is recorded,
// so a run can print (and with --strict fail on) the list of calls that still lack fake data.
//
// Nothing here talks to a real service, and no fixture contains a real key, login code or token.
import { buildState, registerRoutes } from "./fixtures/index.mjs";

export const API_ORIGIN = "https://api.example.test";
/** The fake personal-chat credential the init script stores and the fake API accepts. */
export const FAKE_CREDENTIAL = "shots-fixture-credential-0000";

/**
 * Requests that are deliberately left unanswered and not reported as missing fixtures.
 * Each entry: [method, path regexp, why].  Keep this list short and justified.
 */
export const INTENTIONALLY_IGNORED = [
  // (none yet) -- see the P1.0 delivery note for the reasoning behind every entry added here.
];

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Max-Age": "600",
};

/** Route table: method + path pattern ("/agent-chat/bots/:id/read" or a RegExp) -> handler(ctx). */
function createRouter() {
  const table = [];
  function add(method, pattern, handler) {
    const names = [];
    const regexp = pattern instanceof RegExp ? pattern
      : new RegExp(`^${pattern.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/:([A-Za-z_]+)/g, (_, name) => { names.push(name); return "([^/]+)"; })}$`);
    table.push({ method: method.toUpperCase(), regexp, names, handler });
  }
  const route = (method, pattern, handler) => add(method, pattern, handler);
  for (const method of ["get", "post", "put", "patch", "delete"]) route[method] = (pattern, handler) => add(method, pattern, handler);
  route.match = (method, path) => {
    for (const entry of table) {
      if (entry.method !== method) continue;
      const found = entry.regexp.exec(path);
      if (!found) continue;
      const params = {};
      entry.names.forEach((name, index) => { params[name] = decodeURIComponent(found[index + 1]); });
      return { entry, params, groups: found.slice(1) };
    }
    return null;
  };
  return route;
}

/** Response helpers for fixture handlers (a plain return value is sent as 200 JSON). */
export const reply = {
  status: (status, body) => ({ __reply: true, status, body }),
  /** A Server-Sent-Events body: events is [{event, data}], sent whole. */
  sse: (events) => ({ __reply: true, status: 200, contentType: "text/event-stream", body: events.map(({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("") }),
  text: (text, contentType = "text/plain; charset=utf-8") => ({ __reply: true, status: 200, contentType, body: text }),
};

/**
 * Install the fake API on a browser context.  Returns { state, unmatched, requests }.
 *  - label: the page name recorded with every unmatched request
 *  - unmatched: shared array that receives { page, method, path }
 */
export async function installMockApi(context, { label, unmatched, fixtureState = buildState() }) {
  const route = createRouter();
  registerRoutes(route, reply);
  const seen = [];

  await context.route(() => true, async (pending) => {
    const request = pending.request();
    const url = new URL(request.url());
    // Pages are served by our own static server; the API origin is the fake backend; anything else is blocked.
    if (url.origin !== API_ORIGIN) {
      if (url.hostname === "127.0.0.1" || url.protocol === "data:" || url.protocol === "blob:") return pending.fallback();
      return pending.abort("blockedbyclient");
    }
    const method = request.method().toUpperCase();
    if (method === "OPTIONS") return pending.fulfill({ status: 204, headers: CORS });
    const path = url.pathname.replace(/\/+$/, "") || "/";
    seen.push({ method, path, query: url.search });
    const matched = route.match(method, path);
    const ignored = INTENTIONALLY_IGNORED.find(([m, re]) => m === method && re.test(path));
    if (!matched) {
      if (!ignored) unmatched.push({ page: label, method, path });
      return pending.fulfill({ status: 404, headers: { ...CORS, "Content-Type": "application/json" }, body: JSON.stringify({ detail: "shots: no fixture" }) });
    }
    let body = null;
    const raw = request.postData();
    if (raw) { try { body = JSON.parse(raw); } catch { body = raw; } }
    const headers = request.headers();
    const authed = headers["x-chat-session"] === FAKE_CREDENTIAL;
    try {
      const result = await matched.entry.handler({ params: matched.params, query: url.searchParams, body, state: fixtureState, authed, method, path, headers });
      if (result && result.__reply) {
        return pending.fulfill({ status: result.status, headers: { ...CORS, "Content-Type": result.contentType ?? "application/json" }, body: typeof result.body === "string" ? result.body : JSON.stringify(result.body ?? {}) });
      }
      return pending.fulfill({ status: 200, headers: { ...CORS, "Content-Type": "application/json" }, body: JSON.stringify(result ?? {}) });
    } catch (error) {
      unmatched.push({ page: label, method, path, error: String(error?.message ?? error) });
      return pending.fulfill({ status: 500, headers: { ...CORS, "Content-Type": "application/json" }, body: JSON.stringify({ detail: "shots: fixture handler failed" }) });
    }
  });
  return { state: fixtureState, requests: seen };
}

/** One line per distinct unmatched request: "page METHOD /path". */
export function summarizeUnmatched(unmatched) {
  const keys = new Map();
  for (const item of unmatched) {
    const key = `${item.method} ${item.path}${item.error ? ` [handler error: ${item.error}]` : ""}`;
    if (!keys.has(key)) keys.set(key, new Set());
    keys.get(key).add(item.page);
  }
  return [...keys].map(([key, pages]) => ({ request: key, pages: [...pages] }));
}
