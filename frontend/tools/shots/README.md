# shots: screenshots, pixel compare and smoke checks without a backend

Drives the **built** frontend in headless Chromium with a fake API. It is its own package: it does not touch the app's
`package.json` or `node_modules`, and nothing here ships in the build.

Normally run it through `fe-check.sh` (it builds with `VITE_API_BASE_URL=https://api.example.test` and
`VITE_BASE_PATH=/FinBot/` first). By hand, from this directory:

```
npm ci                                  # playwright-core 1.65.0, pngjs, pixelmatch (uses the browser already in ~/.cache/ms-playwright)
node run.mjs --dist ../../dist --out out/a [--pages a,b] [--widths 390,1440] [--themes light,dark] [--locale zh-CN] [--strict]
node compare.mjs out/a out/b [--out out/diff] [--max-diff-pixels 0]
node smoke.mjs --dist ../../dist [--strict]
```

- `run.mjs` writes `<page>.<theme>.<width>.png` plus `report.json` (per-shot `console.error` / `pageerror`, and the list of
  API requests no fixture answered). `--strict` fails when that list is not empty.
- `compare.mjs` compares same-named PNGs; a size change or a missing file counts as a difference. Exit code 1 on any.
- `smoke.mjs` prints PASS / FAIL per check; any FAIL exits 1.

## Determinism
Fixed system time (2026-11-13 10:00 Beijing), seeded `Math.random`, reduced motion, all CSS animation/transition/caret off,
fonts and network idle awaited, the chat transcript pinned to its bottom, single-threaded software raster. Two runs of one
build must compare with 0 different pixels; if they do not, fix the tool, do not raise the threshold.

## Adding a page
Append to `PAGES` in `pages.mjs`: `{ name, hash, ready, before?, identity? }`.
`ready` is a selector that only exists once the page shows its data (waitReady also waits for "正在读取…" style text to go);
`before(page, { width })` may click or scroll before the shot. Keep `name` stable when a route moves; change only `hash`.
`identity: "none"` opens without credentials (the guest/personal entry page).

## Adding fake data for an endpoint
1. Find the request in `src/api.ts`; the URL is `<api base>` + path with the `/api` prefix dropped (`/agent-chat/...`, `/v2/...`).
2. Write the data in `fixtures/<domain>.mjs` and register the route in `fixtures/index.mjs`:
   `route.get("/path/:id", ({ params, query, body, state, authed }) => data)`; use `own(...)` for owner-only endpoints
   (403 without the fake credential) and `reply.status(404, {...})` / `reply.sse([...])` for other responses.
3. Mutable things (sent chat messages, queue) live in `buildState()`, which is rebuilt for every browser context.
4. Content must be invented: no real keys, login codes, tokens or personal data. Ids are fixed fake UUIDs from `fixtures/ids.mjs`.

An API call with no fixture gets `404 {"detail":"shots: no fixture"}` and is listed at the end of every run.
A request that must stay unanswered goes in `INTENTIONALLY_IGNORED` in `mock-api.mjs`, with the reason.

## Adding a smoke check
Write one named async function in `smoke.mjs` (throw to fail, return a short detail string) and register it in `CHECKS`.
