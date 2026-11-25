# 4e 「它眼中的你」 Implementation Plan — one page for everything it remembers and guesses about the owner, editable, deletable, exportable

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The memory page (`#/assistant/memory`, tab 画像) becomes 「它眼中的你」: one page that shows everything the system keeps about the owner — what he said, what it guessed (and whether he confirmed it), his views of companies with their whole history and the latest look back (4d), what it is watching for him, when it will next tidy its memory, and the exact profile text the model reads every turn — where every item can be changed or removed, and from which the whole lot can be downloaded as one file (JSON for machines, Markdown for reading). The existing profile section stays as it is; this slice only adds what is missing.

**Architecture:** A new read-only module `app/memory_overview.py` gathers, in one place, what the page lacks and what the export needs: `collect(owner_hash) -> dict` (counts, every view version grouped by company with its latest review, watch settings, memory calendar, the profile block the default bot reads) and `export(owner_hash, fmt) -> (bytes, filename, media_type)` (the same data plus every profile item and the conversation summaries, rendered as JSON or Markdown). Two GET routes serve them. Views get two owner-only page writes that reuse `owner_views.record` / `owner_views.drop` (改 = a new version, 撤回 = dropped; history kept, exactly as in chat). The web replaces `OwnerViewsPanel` with a fuller views section and adds a summary head, a 盯防 section, a memory-calendar line, a 「它每轮实际读到的」 fold and an 「导出」 menu; `ProfilePanel` and the 往事 tab are not rewritten.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy (Postgres), pytest; React + TypeScript, node `--test` for `.mjs` helpers.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §6.3 (它眼中的你：一页列出它记住的关于你的一切和它的推测，可以改、可以删、可以整体导出。「放心把信息交给它」需要这一页), §6.1 (三种记忆：个人记忆条目、你的看法、对话原文), §6.2 (明说的和推测的分开；新的盖旧的，旧的不删), §7.3 (规则存在档案的「盯防条件」里，也出现在「它眼中的你」那一页), §十一 (网页要改：「它眼中的你」). Handoff `docs/handoff/2026-11-25-new-kernel-stage4.md` 第二部分第 2 条（记忆页已覆盖大部分，缺导出、缺「看法+画像+推测」的统一视图）.

## 现状与缺口（规划时逐个核过代码，main `81656ca` + 分支 `claude/stage4d`）

Already there — **do not rebuild**:

- `frontend/src/app/assistant/memory/MemoryPage.tsx`: tabs 画像 / 往事 (`?tab=recall`). 画像 = `OwnerViewsPanel` + `ProfilePanel`.
- `ProfilePanel.tsx` (162 lines) over `GET/POST /agent-chat/profile`, `PATCH /profile/{id}` (text, layer), `POST /profile/{id}/confirm`, `POST /profile/{id}/restore`, `DELETE /profile/{id}`: layers 全局 / each bot / 已删除的 bot; origin badges (推断 in the opinion colour with 确认); 长期 label; 「我的推测（未经你确认）」 group with examples and 对 / 不对; 已归档 fold with reason, date, 恢复, 删除; add row. This already covers "说过的 + 推断的 + 待确认的推测 + 归档" for profile items.
- `RecallPanel.tsx` (往事): past conversations, read-only, search.
- Company page (`OwnerViewCard.tsx`): current view, history, 4d 「回头看」, delete one version, restore an archived view.

Missing — **this slice**:

1. **No export of anything memory-related.** (Only a skill's Markdown export, `GET /agent-chat/skills/{id}/export`, and the browser-local chat archive JSON in 设置 → 数据 exist.)
2. **Views on the memory page are thin:** `OwnerViewsPanel.tsx` lists only active views (`GET /agent-chat/views` → `owner_views.all_current`), read-only. Archived, superseded and dropped versions, the 4d review, and any way to change or withdraw a view from the page are absent (withdrawing is chat-only via `drop_view`; there is no page write for a new version).
3. **Watch settings are nowhere on this page** (design §7.3 says they must be): portfolio plans `portfolio_plans` (补仓价/止损价/目标价/文字计划, set on the portfolio page or by `set_position_plan`), alert routines (`agent_tasks` kind `alerts`: filings/news/price lines, on the routines page), research queue (`agent_research_queue`). The sentinel's own price-move rules are code-wide and not per owner (`sentinel/signals.py`); stage 5 makes them adjustable.
4. **No summary** of how much it keeps, and **no view of the memory calendar** (`memory_jobs`: next monthly review, next quarterly settle, last outcome — today only `list_work` in chat knows).
5. **The owner cannot see what the model actually reads** (`agent_profile.render_block` output: the 30-line / 2 KB cut, the 推测 section, the "另有 N 条未显示" line).

## Core-principle check (CLAUDE.md) — decisions made here

- **准则 2 给足提示，用户自判 — the page shows the basis, never filters.** Every item shows where it came from (his words / typed on the page / inferred per turn / monthly guess, confirmed or not / chosen from a template after 4f) and the dates the code holds (`created_at`, `last_seen_at`, `archived_at` + reason). The 「它每轮实际读到的」 fold shows the real block text verbatim, including the 「另有 N 条…」 line, so a cut is visible instead of hidden. The 4d review is shown as the model wrote it, with its stray-figure note when present (unchanged from 4d).
- **准则 1 默认相信模型 — nothing here re-checks or second-guesses stored memory.** The overview and the export are reads; no item is hidden because it "looks unreliable". Rejected proposals are not shown or exported only because the table keeps nothing of them but a hash (`agent_profile._reject`): there is no text to show, and the export says so in one line with the count.
- **准则 3 让模型能力更高 — no new obligation on the model, one small capability.** The model gets no new format or duty. The page writes for views go through the same service functions as `record_view` / `drop_view`, so a view changed on the page reads back in chat exactly like one said in chat (block line 「你的看法（M-D 说的）」). The `open_page` tool can open this page (Task 5 checks the page name list); asked 「你都记得我什么」, the model can answer from its block and offer the page — no new read tool, because the block it needs is already in its context and a full dump would cost every turn.
- **Owner's words stay the authority (4a/4b rule).** A view typed on the page is his words by definition (like a manual profile item: the typed text is its own quote). The model never gains a write here; the two new routes are owner-only page actions mapped in the registry to the existing operations.

## Global Constraints

- **Base:** start from `main` after the 4d PR has merged (`app/view_review.py` and table `view_reviews` exist). If 4d is not merged yet, branch `claude/stage4e` from `claude/stage4d` and rebase onto `main` once 4d merges; never copy 4d code by hand. Check the branch before every commit; WIP-commit before any RED run.
- **Owner only, everywhere.** Every route in this slice calls `_owner_only(x_chat_session)` itself (all GETs pass the public middleware — the handler's own check is the only check, as the comment at `get_research_queue_endpoint` says). Guests get 403 `owner_only`. No owner hash, session, credential, key, token or channel id ever appears in a response or in the export (Telegram/Pushover settings from `sentinel_bridge` are **not** read by this module).
- **`GET /agent-chat/memory/overview`** → JSON:
  - `counts`: `{said, typed, inferred, guesses_confirmed, guesses_waiting, archived, views_current, views_companies, watch}` — all computed by code from the rows (`said` = active origin `explicit`; `typed` = active `manual`; `inferred` = active `inferred`; `guesses_confirmed` = active `pattern`; `guesses_waiting` = `proposed`; `archived` = profile items `archived`; `views_current` = active views; `views_companies` = distinct symbols with any version; `watch` = plans with at least one price or text + enabled alert routines + research-queue symbols).
  - `views`: list of `{symbol, name, current: version|null, versions: [version…]}` ordered: companies with a current view first (newest current first), then the rest by newest version. `version` = `owner_views.serialize(row)` + `review` (latest, `view_review.serialize` shape, or null) — the same shape `GET /views/{symbol}/history` returns. `name` = `owner_views.display_name(symbol)`.
  - `watch`: `{plans: [{symbol, plan_text, add_price, stop_price, target_price, updated_at}], alert_routines: [{id, name, enabled, scope, symbols, filings, news, price_lines, next_run_at, bot_id}], research_queue: [symbols] | null, default_rules_note}`. Plans from `portfolio.load_plans` (skip rows with no price and empty text); alert routines from `agent_tasks` rows of kind `alerts` (`serialize_task` fields, `config` unpacked); queue from `AgentResearchQueue` by owner hash (null when never saved, as `get_research_queue`). `default_rules_note` is a fixed sentence: 「另外，系统默认对你的持仓和研究队列盯价格异动、新公告（哨兵），这些默认规则现在还不能按你单独调整。」 (true today; stage 5 replaces it).
  - `jobs`: one row per `memory_jobs` row of this owner: `{job, title (memory_schedule.JOB_TITLES), next_due (memory_schedule.next_due), last_run_at, last_outcome, last_reason}`; the monthly row also carries `messages_until_early = max(0, review_min_messages() - owner_messages_since(owner, base))`.
  - `seen_block`: the text `agent_profile.render_block(owner, default_bot_id, every_bot=True)` returns for the default bot (`agent_bots.ensure_default_bot(owner).id`), or null. **Read without side effects:** do not call `touch_used`; `render_block` itself writes nothing.
  - Each part is built in its own try: a part that fails is `null` with `errors: ["views"…]` naming it; the rest still returns (one broken table never blanks the page). Logged with the exception type only.
- **`GET /agent-chat/memory/export?format=json|md`** (default `json`; anything else 422 `invalid_format`): returns the file as an attachment, `Content-Disposition: attachment; filename="finbot-memory-YYYYMMDD.json"` (or `.md`), `media_type` `application/json; charset=utf-8` / `text/markdown; charset=utf-8`, date = UTC today.
  - JSON top level: `{"schema": "finbot-memory-export/1", "exported_at": iso, "counts": …, "profile_items": [agent_profile.serialize(row) for every row with status != "rejected", all layers], "rejected_count": n, "views": …(as overview), "watch": …, "jobs": …, "seen_block": …, "conversation_summaries": [{conversation_id, bot_name, seq, created_at, content}], "notes": [fixed sentences]}`.
  - `conversation_summaries`: every `agent_conversation_summaries` row of the owner's conversations (join `agent_conversations.owner_hash`), including archived conversations, oldest first. **Raw messages are not exported in this slice** (see 待 owner 定 1); `notes` says so: 「不含对话原文：原文在每条对话里，也在每夜的数据库备份里。」 and 「被你否掉的推测只留了一个指纹，没有文字，共 N 条。」.
  - Markdown: the same data in sections, headings in Chinese: `# 它眼中的你（导出于 YYYY-MM-DD）` → `## 概览` (counts) → `## 你说过的` / `## 你在记忆页写的` / `## 它推断的` / `## 你确认的推测` / `## 待你确认的推测` (each with example quotes) / `## 已归档` (reason, date) → `## 你对公司的看法` (per company: each version with date, status label, his quote, latest 回头看 verdict label + text) → `## 盯防` → `## 记忆整理日程` → `## 它每轮读到的画像`（fenced as plain text） → `## 对话摘要` → `## 说明`. Every item line carries its layer (全局 / bot 名) and its dates. Pure function `render_markdown(data) -> str`, unit-tested without a DB.
  - Size: no cap needed for profile items (≤ a few hundred rows) and views; summaries are capped at 2,000 rows newest-kept with a note line when cut (「对话摘要只导出了最近 2000 段」). Built with `asyncio.to_thread`.
- **View writes from the page** (owner only; both reuse the service functions, no validation of their own):
  - `POST /agent-chat/views/{symbol}` body `{text: str ≤ 200}` → `owner_views.record(owner, symbol, text, quote=text)` (typed text is its own quote; `conversation_id`/`turn_id`/`source_message_id` null). `ViewError` → 422 with its code (`company_not_recognized`, `invalid_view_text`, `view_quote_too_short` → the page shows 「至少写四个字」). Returns `{status, view, replaced}`.
  - `POST /agent-chat/views/{symbol}/drop` → `owner_views.drop(owner, symbol)`; null → 404 `view_not_found`. Returns `{view}`.
  - Registry (`app/kernel/operation_registry.py`): `("POST", "/agent-chat/views/{symbol}"): _op("record_view")`, `("POST", "/agent-chat/views/{symbol}/drop"): _op("drop_view")` — both go through the same service write path the operations use. `tests/test_operation_registry.py` must pass.
  - A view typed on the page shows 「在记忆页写的」 instead of a conversation link (rule: `conversation_id` null). `owner_views.serialize` gains nothing; the web derives it.
- **What the page must not change:** `ProfilePanel.tsx` behaviour and its requests; the 往事 tab; the company page card (it may reuse the new helpers but its output stays byte-identical in its tests); the kernel prompt, the profile block text, `latest_known`, the old engine. No new background job, no model call anywhere in this slice, no ledger purpose.
- **Web copy:** Simplified Chinese with i18n keys for every new string (`frontend/src/i18n.tsx` dictionary + `npm run test:i18n` clean; any new `scripts/*.test.mjs` is appended to the `test:i18n` list in `frontend/package.json`). Page title stays 「记忆」; the 画像 tab label becomes 「它眼中的你」 (the `?tab` values do not change: none / `recall`).
- **Tests:** backend files you touch plus the new ones, never the whole suite during tasks; no real model call; frontend node tests for every new `.mjs` helper. Screenshots 1440 and 390 in a scratch copy (`node smoke.mjs --only memory`), never the full smoke run.

## Review Focus

1. A guest session on `/memory/overview`, `/memory/export`, `POST /views/NVDA`, `POST /views/NVDA/drop` → 403; another owner's data never appears (two owners seeded in the test).
2. Overview with one company having three versions (active, superseded, dropped) and an archived view on another company, one review row (4d) → `views` has both companies, the active one first, every version present with its review; the counts match the rows.
3. `POST /views/NVDA {"text": "估值太高，先不加仓"}` with an active view → the old one `superseded` with `ended_at`, the new one active with `quote == text` and null conversation; `/views/NVDA/drop` → `dropped`; the 「系统最新掌握」 view line follows (reuse the 4a test helper).
4. Export JSON contains every non-rejected profile item of every layer (including archived and proposed with examples), every view version with its review, the summaries of an archived conversation, `rejected_count`, and no field named like `owner_hash`, `credential`, `token`, `key`, `chat_id` anywhere (walk the JSON in the test). Markdown export of the same seed contains each item text exactly once in its section.
5. `seen_block` equals what a default-bot turn gets (`render_block(..., every_bot=True)`) and reading the overview does **not** change any `last_used_at`.
6. The `views` part raising (monkeypatch) → overview still 200 with `views: null`, `errors: ["views"]`; the page shows an error bar in that section only.
7. The registry test passes with the two new routes; no other mutating route was added.

---

### Task 1: the overview and export module (backend)

**Files:** create `app/memory_overview.py`; modify `app/owner_views.py` (one reader); create `tests/test_memory_overview.py`.

- [ ] `owner_views.all_versions(owner_hash) -> list[dict]`: every version of every company, grouped as `{symbol, name, current, versions}` in the order of Global Constraints; attach the latest review exactly as `history()` does (`view_review.latest_by_view`, same guarded import and warning on failure). Reuse `serialize`; no new columns.
- [ ] `memory_overview.collect(owner_hash) -> dict` with the parts `counts`, `views`, `watch`, `jobs`, `seen_block`, `errors` (each part in its own try, as specified). Helpers `_counts(db, owner)`, `_watch(db, owner)`, `_jobs(owner)`, `_seen_block(owner)`. Read plans with `portfolio.load_plans`, the queue with `db.get(AgentResearchQueue, owner_hash)` (the `memory_settle._queued` pattern), alert routines with a `select(AgentTask).where(owner, kind == "alerts")` + `agent_tasks.serialize_task`.
- [ ] `memory_overview.export(owner_hash, fmt, now=None) -> tuple[bytes, str, str]` building the JSON document (Global Constraints) from `collect` + `agent_profile.list_items(owner, include_archived=True)` (already excludes rejected) + a rejected count + `_summaries(owner)`; `render_markdown(doc) -> str` pure; `fmt` not in (`json`, `md`) → `ValueError("invalid_format")`. JSON with `ensure_ascii=False, indent=2`.
- [ ] Tests `tests/test_memory_overview.py`: Review Focus 2, 4, 5, 6 (seed with the helpers used by `tests/test_owner_views.py`, `tests/test_memory_review.py` and `tests/test_view_review.py`; a review row inserted directly); `render_markdown` on a hand-built dict (no DB) checks section order and that an empty section prints 「（没有）」 rather than disappearing; the summary cap note at 2,000 (monkeypatch the cap to 2 in the test).

### Task 2: routes and the view page writes (backend)

**Files:** `app/agent_chat_stream.py` (beside the existing `/profile` and `/views` routes, same style: `asyncio.to_thread`, `_owner_only`), `app/kernel/operation_registry.py`, tests `tests/test_memory_overview_api.py` and additions to `tests/test_owner_views.py`.

- [ ] `GET /agent-chat/memory/overview` → `collect`.
- [ ] `GET /agent-chat/memory/export?format=` → `Response(content, media_type, headers={"Content-Disposition": ...})`; 422 on a bad format.
- [ ] `POST /agent-chat/views/{symbol}` (`ViewWrite` pydantic body, `extra="forbid"`, `text` max 400 at the edge, the service enforces 200) and `POST /agent-chat/views/{symbol}/drop`. Declare them so they do not shadow `GET /views/{symbol}/history` or `POST /views/{view_id}/restore` (different methods/literals; add a test that `restore` still routes).
- [ ] Registry entries (Global Constraints).
- [ ] Tests: Review Focus 1, 3, 7; export headers (filename pattern, media type); a view text of 3 characters → 422 `view_quote_too_short`.

### Task 3: the views section and the summary head (web)

**Files:** `frontend/src/api/memory-overview.ts` (new: types mirroring the JSON, `getMemoryOverview`, `downloadMemoryExport(format)`, `writeOwnerView(symbol, text)`, `dropOwnerView(symbol)`), `frontend/src/memory-overview.mjs` + `.d.mts` (new pure helpers), `frontend/scripts/memory-overview.test.mjs` (new, added to `test:i18n`), `frontend/src/app/assistant/memory/OwnerViewsPanel.tsx` (rewritten to the fuller section), new `MemorySummary.tsx`, `MemoryPage.tsx` (layout + tab label), i18n.

- [ ] Helpers in `memory-overview.mjs`: `summaryLine(counts)` → the ordered list of `{key, label, value}` shown in the head (zero values kept, so "0 条推测" is visible); `viewGroups(views)` (current first; a company with only ended versions shows under 「以前的看法」); `typedOnPage(version)` (`conversation_id == null`); `jobLine(job, locale)` → 「下次每月整理：12月25日前后（再发 N 条消息会提前）」 / 「下次每季整理：2027年2月15日」 / last outcome phrase from `last_outcome` (`done` 上次整理完成 / `skipped` 上次跳过：reason / `failed` 上次出错，稍后重试); `exportFilename(format, now)`. Node tests for each, including empty inputs.
- [ ] `MemorySummary.tsx`: the head under the page title — one sentence 「这是系统记得的关于你的一切，以及它的推测。都可以改、删，也可以整体导出。推测只影响回答的详略和先后，不影响结论。」, the counts line, the calendar lines, the 「导出」 button (a menu: 「导出 JSON（完整）」/「导出 Markdown（好读）」; download with the session header via `fetch` → `Blob` → object URL → temporary anchor, copying the pattern in `frontend/src/app/assistant/skills/SkillsPage.tsx`; revoke the URL after click; an error goes to `ErrorBar`).
- [ ] `OwnerViewsPanel.tsx` (keeps its test ids `owner-views`, `owner-view-item`, `owner-view-link`, `owner-view-quote`): data from `getMemoryOverview().views` (one request for the whole page: lift the load into `MemoryPage` and pass the parts down; `ProfilePanel` keeps its own `/profile` load). Per company card: symbol + name, current text, his quote (or 「在记忆页写的」), date; the latest 回头看 badge + text + basis line + stray-figure note **reusing** `verdictBadge`, `basisLine`, `strayFigures`, `reviewOf` from `owner-views.mjs`; buttons 「改」 (inline input, max 200, save → `writeOwnerView`, then reload), 「撤回」 (confirm dialog 「撤回后它不再按这条看法回答，历史里还留着。」 → `dropOwnerView`), 「历史 · N」 fold listing every version with `versionSpan` and status label, each with 「删除」 (existing `deleteOwnerView`, existing confirm copy from the company card) and, for archived, 「恢复」 (existing `restoreOwnerView`, 409 text from `restoreFailText`). Companies with no current view are listed under 「以前的看法」 with the same fold and a 「重新写一条」 button (same input).
- [ ] i18n keys for all strings; `npm run test:i18n`.

### Task 4: watch settings, the seen-block fold, and the profile badge copy (web)

**Files:** new `frontend/src/app/assistant/memory/WatchPanel.tsx`, new `SeenBlockFold.tsx`, `MemoryPage.tsx`, `memory-overview.mjs` (+ tests), i18n.

- [ ] `WatchPanel.tsx` 「它在帮你盯的」: three short lists — 「持仓计划」 (symbol · 补仓 X · 止损 Y · 目标 Z · 文字计划; link 「去持仓页改」 → the portfolio route in `routes.mjs`), 「盯盘任务」 (name · 范围 · 申报/新闻/价位线 · 下次运行 · 已暂停 when disabled; link 「去例行任务改」), 「研究队列」 (symbols; link to the research page), then `default_rules_note` in muted text. Empty list → 「（没有）」 line, never hidden. Read-only here: edits stay on their own pages (no duplicate editors). Helper `watchRows(watch)` in `memory-overview.mjs` formats numbers with the existing price formatter used by `PriceLineRows.tsx` (import, do not copy).
- [ ] `SeenBlockFold.tsx` 「它每轮实际读到的」: a collapsed `Collapsible` showing `seen_block` in a `<pre>` (wrap, monospace, no Markdown rendering), with one sentence 「这是默认 bot「助理」每轮对话前读到的画像原文；条目多时会截断，截掉的仍在上面的列表里。」; null → 「现在没有画像，它每轮什么都不读。」.
- [ ] Page order on the 「它眼中的你」 tab: `MemorySummary` → `OwnerViewsPanel` → `ProfilePanel` (unchanged) → `WatchPanel` → `SeenBlockFold`. A failed part (`errors` contains it) shows `ErrorBar` with retry in that section only (Review Focus 6).
- [ ] Screenshots 1440 and 390 in a scratch copy with fixtures: add `GET /agent-chat/memory/overview` to the shot fixtures (seed: 3 profile layers, 2 proposed, 1 archived, 2 companies with views incl. a review with a stray figure, 1 plan, 1 alert routine, queue of 3, both jobs, a block text). `npx tsc -b`, `npm run build`.

### Task 5: the model's way to the page (backend, small)

**Files:** `app/agent_tool_catalog.py` (`PageArgs`), tests next to the existing `open_page` tests.

- [ ] Check `PageArgs`' page names: if the memory page is not one of them, add it (name `memory`, path `/assistant/memory`) following the existing entries, and pin it in the existing page-list test. If it is already there, change nothing and note it in the report. No other tool, prompt or description changes (the kernel system text stays byte-identical; pinned tests must not move).

### Task 6 (controller)

- [ ] Related tests, then the full suite on the final commit (`.venv-rag/bin/python -m pytest -q -W ignore tests/`; the two known order-dependent failures excepted); frontend `npm run test:i18n`, `npx tsc -b`, `npm run build`, the two screenshots.
- [ ] Shadow (needs the box): `ruler_shadow.sh up`, deploy the branch to `ruler-src`, call `/memory/overview` and both exports with the owner session on real data; read the Markdown end to end; check the file has no secret (grep for `token`, `key`, `hash`, `chat_id`); `down`.
- [ ] Report `docs/reports/2026-11-stage-4e.md`; backlog entry; PR; check CI myself; merge and ship under the standing rule (backup before the API swap).

## 待 owner 定

1. **导出要不要包含对话原文。** 推荐：这一片不含（只含对话摘要）；原文量大，往事页能查，每夜有数据库备份。要的话后续加一个「含对话原文」勾选，只导出 owner 自己的消息和最终回答。计划按「不含」实施，文件里写明。
2. **「它眼中的你」做成记忆页的画像页签（改名），还是单独一个新页面。** 推荐：改记忆页画像页签的名字和内容（地址不变，旧链接不坏，不多一个入口）。计划按此实施。
3. **页面上改看法要不要也出确认卡。** 推荐：不要——这是本人在自己的页面上亲手改，和记忆页改画像文字一样直接生效，历史版本保留可查可删。计划按此实施。
