# shots: screenshots, pixel compare and smoke checks without a backend

Drives the **built** frontend in headless Chromium with a fake API. It is its own package: it does not touch the app's
`package.json` or `node_modules`, and nothing here ships in the build.

Normally run it through `fe-check.sh` (it builds with `VITE_API_BASE_URL=https://api.example.test` and
`VITE_BASE_PATH=/` first (the root path, as on finbotai.me)). By hand, from this directory:

```
npm ci                                  # playwright-core 1.65.0, pngjs, pixelmatch (uses the browser already in ~/.cache/ms-playwright)
node run.mjs --dist ../../dist --out out/a [--pages a,b] [--widths 390,1440] [--themes light,dark] [--locale zh-CN] [--strict]
node compare.mjs out/a out/b [--out out/diff] [--max-diff-pixels 0]
node smoke.mjs --dist ../../dist [--strict] [--only <text in a check name>]
```

- `run.mjs` writes `<page>.<theme>.<width>.png` plus `report.json` (per-shot `console.error` / `pageerror`, and the list of
  API requests no fixture answered). `--strict` fails when that list is not empty.
- `compare.mjs` compares same-named PNGs; a size change or a missing file counts as a difference. Exit code 1 on any.
- `smoke.mjs` prints PASS / FAIL per check; any FAIL exits 1. `--only <text>` runs just the checks whose name contains it.
- `utility-legacy-collisions` (smoke, no browser, reads `<dist>/assets/*.css` and `<dist>/../src`): fails when a class the built `utilities` layer defines is also an old class name (`src/styles/legacy/*.css`, `className` strings of the old `.tsx` in the `src/` root). Tailwind scans `src/app`, `src/components`, `src/dev`, and a word in a comment there (`table`, `contents`…) becomes a utility that beats the `legacy` layer. Fix by rewording or moving the code; `ALLOWED` in `collisions.mjs` takes an entry only with a reason.

## Determinism
`settle()` forces one layout of every native `<select>` after the fonts are ready (a select lays its text out once, and a web font that lands later leaves it 1px off, depending on when the page mounted it).
Fixed system time (2026-11-13 10:00 Beijing), seeded `Math.random`, reduced motion, all CSS animation/transition/caret off,
fonts and network idle awaited, the chat transcript pinned to its bottom, single-threaded software raster. Two runs of one
build must compare with 0 different pixels; if they do not, fix the tool, do not raise the threshold.

## Adding a page
Append to `PAGES` in `pages.mjs`: `{ name, hash, ready, before?, identity? }`.
`ready` is a selector that only exists once the page shows its data (waitReady also waits for "正在读取…" style text to go);
`before(page, { width })` may click or scroll before the shot. Keep `name` stable when a route moves; change only `hash`.
`identity: "none"` opens without credentials (the login page); `identity: "guest"` opens as a read-only guest (mode stored, no credential).

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

## P2.2 views and fakes
- Pages `shell-collapsed` (1440: the sidebar folded), `shell-mobile-more` (390: the 更多 drawer open), `shell-bot-states` (the four bot-row marks: 1440 shows the sidebar, 390 the drawer), `login-error` (a wrong code was sent), `guest-chat` (read-only chat). `shell-collapsed` and `shell-mobile-more` only do something at the width they are named for; run them with `--widths 1440` / `--widths 390`.
- `shell-bot-states` makes the four states from the fixtures: NewsBot has unread, ReportBot has a pending item (the amber dot), and the page sends `[hold-the-answer]` in TeslaBot's line: the fake stream never answers a message holding that marker (`HOLD_MARKER` in `fixtures/ids.mjs`), so that row shows 回答中.
- `POST /agent-chat/personal-login` answers a credential for `LOGIN_CODE` (an invented code) and 401 for any other.

## P3.1 chat checks (`--only chat-` runs the nine; every package that touches the chat page runs them again)
`chat-send`, `chat-cancel`, `chat-background-line`, `chat-clarification`, `chat-write-confirm`, `chat-readonly-archive`, `chat-external-sync`, `chat-compact`, `chat-load-earlier` (design 7.3, P3.1 row).
- `fake-sse.mjs`: the fake API answers a request whole, so it cannot leave a stream half-open.  `handFed(page)` wraps `window.fetch` in the page: a POST to `/agent-chat/stream` whose message holds `[hand-fed]` gets a stream the check feeds (`push`) and ends (`close`) by hand; abort errors it like the browser does.  Everything else still goes to the fake API.
- Markers in a message (fixtures/ids.mjs): `[hold-the-answer]` never answers; `[ask-which]` answers with a clarification card and the turn ends `waiting_for_input`; `[hand-fed]` is the page-side stream above.
- State a check can set up: `state.chat.older[conversationId] = { messages, cursor }` makes the newest page say "earlier turns exist" and serves them for `?before=`; `POST .../conversations/:id/compact` leaves a `已压缩 2 轮` notice in `state.chat.compactions`.  A turn pushed into `state.chat.conversations.get(id)` after the page loaded is what the external-sync check treats as written from outside.
- Declining a write card (`先不要`) is not silent: the page sends the turn `cancel` with the card's `pending_request_id` (that is how the server cancels it); the check asserts there is no `confirm:*` request.
- The archive view ends when a bot's line is opened, so `chat-readonly-archive` reads the archive on `#/chat/history`.
- `locale-catalog-on-demand`: the English catalog is a chunk of its own (`en-US-*.js`); a Chinese session never requests it.

## P3.2 chat page: stable hooks, pages, checks
- The chat page's own markup (`src/app/chat/`) carries `data-testid` hooks, so a restyle never touches this tool again: `chat-page`, `chat-header`, `chat-body`, `chat-column`, `bot-line` (the 2px signature line), `transcript` (the scroll box), `thread`, `message` (+ `data-role=user|assistant`, `data-last`, `data-kind=task-post`), `user-bubble`, `message-body` (`data-md=ready|plain`, `data-streaming`), `markdown-skeleton`, `markdown-failed`, `message-foot`, `copy-question`, `jump-bottom`, `load-earlier`, `compaction`, `archive-banner`, `return-live`, `welcome`, `composer`, `draft` (also `#agent-draft`), `send` / `stop` (one button, two states, one place), `slash-menu`, `model-badge`, `context-meter`, `chat-status`, `side-toggle`, `bot-settings`, `about-chat`, `history-toggle`, `history-list`, `question-rail`, `turn-preview`. Panels opened from a button are `[data-slot=pop-panel]`.
- Pages: `chat-streaming` (an answer half way, stop showing), `chat-scrolled-up` (a long streamed answer, reader scrolled up, 回到底部 on screen), `chat-slash-menu`, `chat-model-picker`, `chat-empty-composer` (TeslaBot's line is empty in the fixtures: the empty state with a focused composer).  `pages.mjs` exports `streamHalfway(page, { paragraphs })` and `streamParagraph(n)` for checks that need a hand-fed answer.
- Checks: `composer-ime`, `composer-slash-menu`, `chat-follow-and-jump`, `draft-survives-switch`, `stop-button`, `copy-toast`, `chat-question-rail`, `markdown-chunk` (the renderer chunk, `markdown-renderer-*.js`: asked for before the history request; a skeleton while it is held 2 s; plain text + 重试 when aborted, 重试 recovers).
- `chat-readonly-archive` changed with the page: a read-only archive replaces the composer with 返回当前对话 (`return-live`) instead of disabling it.

## P3.3 process and sources (`--only citation-jump`, `steps-`, `public-mark`, `legacy-line-mark`, `old-message`, `panel-resize`, `sources-keyboard`, `source-card` run them)
- Pages: `chat-sources` (a citation chip clicked: the 来源 tab on card 2, the one-shot mark kept on for the picture), `chat-process` / `chat-default-thinking` (the 过程 tab; the first also has a tool step's 原始数据 open), `chat-steps-running` (a hand-fed turn: one step turning, two tools done with 3 and 12 hits), `chat-public-mark` (a mark's card pinned open), `chat-old-message` (AppleBot: an answer with only a time), `chat-panel-collapsed`.
- `pages.mjs` exports `streamSteps(page)` (the hand-fed half-way turn above) and `traceEvent(id, kind, fields)` (a trace event as the server sends it).
- Fake data: `GET /knowledge/citations/:id` answers `CITATION_DETAILS` (chunk `k…01` a saved filing, `k…02` a derived AI analysis; any other id is a withdrawn source, 404). The default line's first answer has three tool results (3 hits, none, a failure); its second answer ended `partially_succeeded`; its third point carries an old-style unverified-line mark; AppleBot's answer has only `thinking_ms`; NewsBot's has only a `tool_trace`.
- `public-mark-verbatim` imports `chat-public-marks.mjs` from `../../src` and computes the card's three texts for the fixture message; the page must show them word for word. It resolves `--danger`, `--action`, `--action-soft` and fails if the mark or its card (any descendant) uses one of those colours or holds an icon, in light and dark.

## A1 avatar checks (`--only avatar` runs them with `idle-avatars-no-raf`)
- `#/dev/kit/bots` (needs the dev kit build, `fe-check.sh` makes one): the five bots at size L with a row of buttons that puts all of them in one state (`data-scenario="<name>"`). Each avatar's `svg[data-slot=bot-body]` carries what the checks read: `data-clock` (engine clock, seconds), `data-tempo`, `data-state`, `data-pose`, `data-gaze`, `data-waiting`, `data-dim`. The sample page sets `unlimited` on its avatars (a real page runs one M / L avatar at a time; see `components/bot/bot-loop.ts`).
- `avatar-no-react-frames` counts React commits through a fake `__REACT_DEVTOOLS_GLOBAL_HOOK__` and `requestAnimationFrame` calls for 3 s on the chat page; `avatar-tempo-differs` compares the five clocks' advance with their tempos; `avatar-ring-hue` reads the thinking ring's gradient stops (computed `stop-color`) against the body's own hue; `avatar-rest-gaze` reads the gazes and the eyes' positions; `avatar-waiting-pose` ends a turn with a card in TeslaBot's line and samples the header avatar for 10 s.
- Pages `dev-kit-bots-<state>` (12): reduced-motion still frames of the five bots in each state.
