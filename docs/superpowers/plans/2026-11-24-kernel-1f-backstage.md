# 1f-1 Backstage Implementation Plan — one place to see every answer, every model call and what it cost

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner opens one read-only page and sees, for any answer, the whole course of the turn; and, for any day, model or bot, how many model calls were made, for what, and what they cost.

**Architecture:** A model-call ledger written at the few places the app calls a model provider, tagged with a purpose set where the work starts (a chat turn, a summary, a judge, a forecast…). Owner-only read endpoints under `/backstage` read the ledger, the stored assistant messages, the consent table and the outbox. A new page `#/backstage` with four tabs shows them. Nothing on the page can change a record.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, PostgreSQL, pytest; React + TypeScript (Vite), the frontend's existing UI kit and i18n.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §9.2 (后台) and the stage-1 row of §十二 (「后台『回答』栏和用量记录」). This slice does the 回答, 用量, 操作记录 and 提醒投递 tabs: the data for the last two already exists. 值班, 记忆变更 and 质量 come with the features they show. 「被事件叫醒」 is the next slice (1f-2).

## Global Constraints

- **Read-only.** No endpoint under `/backstage` writes, and the page has no control that changes a record.
- **Owner only.** Every `/backstage` endpoint answers 403 `owner_only` to anyone else (the existing `_owner_only` check in `app/agent_chat_stream.py`). The nav entry is shown only to the owner.
- **No secrets.** No API key, card token, button value, `identity_credential`, bearer token or full provider URL is stored in the ledger or returned by any endpoint. Card values in stored turns are never shown (the existing stored records already exclude them; check that nothing new adds them).
- **The ledger never breaks a call.** Writing a ledger row is best-effort: a failure is logged once and swallowed; it never delays the model call's result by more than the insert, and never runs inside the provider's retry loop twice for one call.
- **Every model call counts once**, including retries (each attempt is a row, marked `attempt`), failed calls (`ok=false`, with a short code), and calls from background work (forecasts, earnings reading, material analysis, summaries, profile extraction, the claim judge, query expansion, localisation, knowledge extraction, routines).
- **Cost is configuration, never guessed.** A catalog entry may carry prices per million tokens (input, output, cache read, cache write). A call to a model with no price shows tokens and 「未设价格」, never a made-up figure. Prices are edited where models are edited (settings → models).
- Copy is Simplified Chinese with English locale entries, as the rest of the frontend.
- Old-engine turns are shown with whatever they stored; nothing is backfilled or rewritten.
- Tests: `/Users/wupeng/Monash/monash-ai/projects/market-evidence-agent/.venv-rag/bin/python -m pytest -q -W ignore <files>` for the files you touch; do not run the whole suite (the controller runs it once before the PR). Two tests fail on main for unrelated reasons (`test_sw1_existence_knowledge::test_t39…`, `test_sw1b_sample_aggregate::test_b17…`). The worktree's `frontend/node_modules` is a dangling link: list frontend files you change and the controller runs the frontend tests and build.
- Commit with a plain-English message, files by name.

## Review Focus

1. A guest, or the owner's credential missing or wrong, on every `/backstage` endpoint: 403, and no row content in the body.
2. A provider call that raises, times out or is retried: exactly one ledger row per attempt, the caller sees the same exception or result as before, and no secret in the row.
3. A conversation with 2,000 turns, and an assistant message whose stored `tool_calls` is an old-engine shape, malformed JSON or null: the list and the detail endpoints still answer, quickly, with what they can show.
4. Usage for a day that crosses midnight in the owner's timezone versus UTC: say which one the page uses and be consistent between the list and the totals.
5. A model renamed in the catalog (rename now carries bots and roles along): its past calls still show under a recognisable name, and its price applies only from when it was set.

---

### Task 1: the model-call ledger

**Files:**
- Create: `app/model_usage.py`, `tests/test_model_usage.py`
- Modify: the provider choke points — `app/agent_chat_provider.py` (`decision_request`, `stream_decision`, and whatever they share), `app/anthropic_native.py` if it makes the native call itself, `app/event_provider.py` (`DeepSeekEventProvider`), `app/model_providers.py`, `app/knowledge/extraction.py`, `app/agent_chat_api.py` (its direct provider calls); the places work starts, to set the purpose (see below); `app/agent_model_catalog.py` (price fields); the model catalog API and its form (`frontend/src/app/settings/models/`) for prices.

**Interfaces — produces:**
- Table `model_calls` (created by the app's usual `create_all` / `ensure_columns`): `id`, `created_at` (UTC), `owner_hash` (nullable), `purpose` (string ≤ 32), `provider`, `model` (the provider's model id), `catalog_name` (nullable: the catalog entry used, as named at call time), `conversation_id`, `turn_id`, `bot_id` (all nullable), `job` (nullable string ≤ 64: a background job's id or name), `attempt` (int, 1-based), `ok` (bool), `error` (nullable short code ≤ 64), `ms` (int), `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` (ints, 0 when the provider did not say), `streamed` (bool). Indexes on `(created_at)`, `(owner_hash, created_at)`, `(turn_id)`.
- `app/model_usage.py`:
  - `PURPOSES`: `chat`, `summary`, `profile`, `judge`, `forecast`, `earnings`, `material_analysis`, `news`, `routine`, `query_expansion`, `localization`, `knowledge`, `other`.
  - `purpose(name, *, owner_hash=None, conversation_id=None, turn_id=None, bot_id=None, job=None)` — a context manager (contextvars) that tags every call made inside it; nested use overrides only the fields it sets. A call made outside any is `other`.
  - `record(*, provider, model, catalog_name=None, attempt=1, ok, error=None, ms, usage=None, streamed=False)` — one row from the current tags; `usage` is the provider's usage object or dict in any of the shapes the app already handles (OpenAI-style `prompt_tokens`/`completion_tokens`, Anthropic `input_tokens`/`output_tokens`/`cache_read_input_tokens`/`cache_creation_input_tokens`, the kernel's own). Writes off the event loop when called from async code; never raises.
  - `price_of(catalog_entry) -> dict | None` and `cost(row, prices) -> float | None` (USD).
- Catalog entries gain optional `price_input`, `price_output`, `price_cache_read`, `price_cache_write` (USD per million tokens, ≥ 0) and `price_since` (set when any price changes). The models form shows four optional number fields under an 「价格（可选）」 heading with the note 「填了才会在后台算花费；不填只显示用量。」.
- Purposes are set at: the chat stream endpoint for a turn (`chat`, with owner, conversation, turn and bot — this covers both engines and the kernel's backup model), the summariser and compaction (`summary`), the profile extractor (`profile`), the claim judge (`judge`), forecast processing and revision (`forecast`), the earnings reader (`earnings`), material analysis (`material_analysis`), news polling and its model use (`news`), routines / scheduled tasks (`routine`, with the task id as `job`), query expansion (`query_expansion`), localisation (`localization`), knowledge extraction (`knowledge`). Read each entry point; where one already runs inside another's tag (for example query expansion inside a chat turn), the inner tag wins for its own calls.

- [ ] **Step 1: failing tests** in `tests/test_model_usage.py`: usage parsing for each shape (including missing fields → 0); nested purposes; a call outside any purpose → `other`; `record` swallowing a database failure and logging once; one row per attempt when a fake provider fails once then succeeds (drive the real retry code in `agent_chat_provider` with a fake transport); a streamed kernel turn with two model calls → two `chat` rows carrying the turn id; a background entry point (pick the forecast processor and the summariser) → rows with their purpose; no column of any row contains the fake API key, and no `error` is longer than 64; cost with and without prices, and a price set after a call does not apply to it.
- [ ] **Step 2: see them fail. Step 3: implement. Step 4: run the new file plus the existing test files of every module you modified. Step 5: commit.**

### Task 2: backstage read endpoints

**Files:**
- Create: `app/backstage_api.py` (router prefix `/backstage`, registered where the other routers are), `tests/test_backstage_api.py`
- Modify: `app/agent_workflow/models.py` and `app/agent_workflow/consent.py` — `agent_consents` gains `decided_at` (nullable, set when a card is executed, cancelled, changed or expires); nothing else about consent changes.

**Interfaces — produces** (all owner-only, all GET, all JSON):
- `/backstage/answers?bot_id=&engine=v2|v1&status=failed|cancelled|succeeded|waiting_for_input&tier=high&slow=1&q=&before=&limit=50` — newest first, keyset-paginated by `(created_at, id)`. Each item: message id, conversation id, bot id and name, created_at, the user's question (first 200 chars), answer (first 200 chars), engine (`v2` when the stored record says route `K`, else `v1`), status, highest tier, model label(s), total ms, model calls, tokens (total, cache read, cache write), cost when every call of the turn has a price (else null), tool count, write outcomes. `slow=1` means total ms over the p90 of the returned window; say in the response which threshold was used. `q` searches question and answer text.
- `/backstage/answers/{message_id}` — the whole course in time order: the question; each model call (tier, model, ms, tokens, cache, from the ledger by turn id, falling back to `audit.calls`); each narration line and checklist state; each tool call with its name, arguments (with any `confirm:`/`authorize:` value removed) and a result summary (ok, error code, row count, the first 3 row titles); citations; write proposals and outcomes; the final answer; the backup-model label if it was used; the Langfuse trace link when Langfuse is configured and the stored record has a trace id. An old-engine message returns the same top-level shape with the parts it has and `"partial": true`.
- `/backstage/usage?from=&to=&group=day|model|bot|purpose` — totals per group: calls, failed calls, tokens by kind, ms p50, cost (sum of priced calls) and `unpriced_calls`. Days are the owner's timezone if the app has one configured for him, else UTC; the response says which.
- `/backstage/operations?limit=&before=` — consent cards newest first: when proposed, the card's title and targets (as shown to the user), the operations' names and tiers, status, `decided_at`, and the result summary. Never the capability hash or payload digest.
- `/backstage/deliveries` — the outbox list `channels.deliveries` already builds, with paging.

- [ ] **Step 1: failing tests** in `tests/test_backstage_api.py` (real PostgreSQL if the repository's other database tests use it; follow `tests/test_channels*.py`): 403 for guest and missing credential on all five; list filters and keyset paging; detail of a kernel turn with tools, a card and a backup model; detail of an old-engine message and of a message with null / malformed `tool_calls`; a stored button value never appears in any response; usage grouping with priced and unpriced calls and the timezone statement; operations never expose the capability hash; `decided_at` set on execute, cancel and expiry.
- [ ] **Step 2–5** as Task 1.

### Task 3: the backstage page

**Files:**
- Create: `frontend/src/app/backstage/` (page, four tab components, a detail drawer, an API module), `frontend/src/app/pages/backstage.tsx`
- Modify: `frontend/src/routes.mjs` (+ `.d.mts`: `backstage: "/backstage"`, `/backstage/:tab`), `frontend/src/app/router.tsx`, the shell's navigation (owner only), locale files, and the tests that enumerate routes or locale keys.

**Interfaces — consumes** Task 2's endpoints exactly.

- 回答: filter bar (bot, engine, status, 「只看用了高档的」, 「只看慢的」, search box), a table (time, bot, question, status, tier, time taken, calls, tokens, cost), infinite scroll by `before`. A row opens the detail drawer: a vertical timeline in time order (narration, model calls with tier and tokens, tool calls with arguments and result summary, card proposed / pressed, answer), and the citations. A 「Langfuse」 link when present. An old-engine record shows a line 「旧流程的记录，只有部分经过」.
- 用量: date range (last 7 / 30 days / custom), group switch (按天 / 按模型 / 按 bot / 按用途), a table and one bar chart of the chosen grouping using the repository's existing chart component if it has one (else the table only), totals row, and the 「未设价格」 count with a link to settings → models.
- 操作记录: table of cards (time, what, status, decided at, result).
- 提醒投递: the deliveries list (time, source, channel, status, acknowledged).
- Empty, loading and error states for each tab; works at phone width.

- [ ] **Step 1: failing tests** in the frontend's test style (route present; nav entry only for the owner; each tab renders the API's sample payload; a partial record shows the old-engine line; cost shows 「未设价格」 when null). **Step 2–5** as Task 1; list the frontend files changed.

### Task 4 (controller, parallel with Tasks 1–3): inventory of state-changing endpoints

A document, `docs/reports/2026-11-mutating-endpoints.md`: every `POST`/`PUT`/`PATCH`/`DELETE` route in `app/`, grouped by feature, each marked as reachable from the kernel's `act` (operation name), deliberately not offered (why), or a gap (what an owner would say to need it). Ends with the gaps ranked by how often the owner's conversations in the last 30 days asked for something the kernel could not do. No code change.

### Task 5 (controller): verify and ship

Full Python suite once, frontend tests and build in the scratch copy, shadow environment: one chat turn and one summary produce ledger rows with the right purpose; the page rendered against the shadow API with screenshots of each tab. PR, CI, merge, deploy (API first). Live: the ledger fills for real turns; the page loads for the owner. Report, backlog, memory.
