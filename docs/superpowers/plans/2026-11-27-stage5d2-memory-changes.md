# 5d-2 The backstage 「记忆变更」 tab: every change to what it keeps about the owner, with who made it and on what basis

**Goal:** The backstage gets a sixth tab, 「记忆变更」: what was recorded, changed, archived, restored, confirmed or deleted in the owner's memory (profile items) and in his views of companies, newest first, each with who made the change (a chat turn, the memory page, the monthly review, the quarterly settle, a role template, the old pipeline's extraction) and its basis (his quote and the conversation it came from, the review's examples, the settle's reason). Read-only.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §9.2 (「记忆变更：记了什么、改了什么、归档了什么，各自的依据」; 「能筛、能搜、能回放」; 「只读」; 「个人版 owner 可以删除自己的数据」), §6.2 (新的盖旧的，旧的不删；明说的和推测的分开；每月整理、每季沉淀).

**Why a log and not the rows' timestamps:** `agent_profile_items` keeps `created_at`, `confirmed_at`, `settled_at`, `archived_at`, but an edit overwrites `text`, a layer move overwrites `bot_id`, a restore clears `archived_at`, a delete removes the row, and nothing says who did it. So the changes are recorded where they happen, in the same transaction, in an append-only table. What happened before this slice is reconstructed once from the timestamps and marked as reconstructed.

## Task 1 — the log (`app/memory_events.py`, new; model in `app/agent_chat_models.py`)

- Table `memory_events` (model `MemoryEvent` on `Base`, so `Base.metadata.create_all` in `app/main.py` creates it): `id` UUID pk; `owner_hash` String(64) not null; `at` timestamptz not null; `target` String(8) (`profile` | `view`); `item_id` UUID not null (the profile item or the view version); `action` String(16); `by` String(12); `text` String(200) null; `before` String(200) null; `reason` String(200) null; `basis` JSON null; `bot_id` UUID null; `symbol` String(12) null; `reconstructed` Boolean not null default false. Index (`owner_hash`, `at` desc, `id` desc) and (`owner_hash`, `item_id`).
- Actions — profile: `added` (his words: chat, page, template, old extraction), `noticed` (the kernel model's guess on the spot), `proposed` (monthly review), `confirmed`, `edited` (text; `before` = old text), `moved` (layer; `basis.from_bot`/`basis.to_bot`), `archived` (`reason`), `restored`, `settled` (became long-term), `rejected` (he turned a guess down), `deleted`. View: `recorded` (a new version; the one it replaces gets `superseded` with `basis.by_item` = the new version's id), `dropped`, `archived`, `restored`, `deleted`.
- `by`: `chat` | `page` | `review` | `settle` | `template` | `extract` | `unknown`. A consequence of another change (topic replacement, the 30-item cap, the 20-proposal limit) carries the cause's `by` and a `reason` (`replaced` with `basis.by_item`, `cap`, `limit`, `stale`).
- `basis` (JSON, only what applies): `quote`, `message_id`, `conversation_id`, `turn_id`, `examples` (the review's, as stored on the item), `run` (review run id), `template`, `by_item`, `from_bot`, `to_bot`.
- API of the module:
  - `Actor` — a small frozen dataclass or dict `{"by": str, "conversation_id"?, "turn_id"?, "message_id"?, "run"?, "template"?}`; helpers `chat(conversation_id, turn_id, message_id=None)`, `PAGE`, `review(run)`, `SETTLE`, `template(template_id)`, `extract(message_id)`.
  - `log(db, owner_hash, *, target, item_id, action, by, at=None, text=None, before=None, reason=None, basis=None, bot_id=None, symbol=None)` — adds a row to the caller's session; never commits; the caller's commit makes the change and its record together.
  - `scrub(db, owner_hash, target, item_id)` — for a deletion: every earlier event of that item loses `text`, `before` and the quotes in `basis` (`quote`, `examples`); `action`, `at`, `by` stay. The owner deleting his words removes them from the log too (§9.2 个人版可以删除自己的数据; the same reason a rejected guess keeps only a fingerprint).
  - `backfill(owner_hash=None)` — once, idempotent: for every profile item and view version **with no event yet**, reconstruct from the row: profile `added`/`noticed`/`proposed` at `created_at` (by origin and `review_run`: explicit → chat if `source_message_id` else unknown, manual → page, inferred → extract, pattern + review_run → review, pattern without run → chat, `template` set → template), `confirmed` at `confirmed_at`, `settled` at `settled_at`, `archived` at `archived_at` with `archived_reason` (an archived row without `archived_at`: `archived` at `updated_at`, reason null), `rejected` at `updated_at` without text; view `recorded` at `created_at` (basis quote, message, conversation, turn), and by status `superseded` / `dropped` / `archived` (with reason) at `ended_at`. All `reconstructed=True`. Runs at startup after the table exists (`app/main.py`, next to the other `ensure_*`), under `pg_advisory_xact_lock(hashtext('memory_events:backfill'))`. Logged count; a failure is logged and the API still starts.
  - `page(owner_hash, *, target=None, action=None, by=None, q=None, before=None, limit=50)` — newest first, cursor as the other backstage lists (`created_at`/id cursor helpers in `app/backstage_api.py`), `q` searches `text`, `before` and `reason` (ILIKE, escaped as `_like`).

## Task 2 — record every change where it happens

Each mutating function takes `by: Actor | None = None` (None → `unknown`) and calls `memory_events.log` inside its own session before `db.commit()`, for the row it changes and for every row its consequence changes:

- `app/agent_profile.py`: `add_item` (added; a duplicate that upgrades an inferred row to his own words logs `confirmed` with reason `restated`; a plain repeat logs nothing), `add_manual_item` (passes PAGE through), `_evict` (archived, reason `cap`), topic rivals archived in `add_item` and `_replace_topic` (archived, reason `replaced`, `basis.by_item`), `archive_item` (archived; a pattern row → `rejected`, then `scrub`), `restore_item` (restored), `delete_item` (deleted + `scrub`; pattern → rejected + `scrub`), `confirm_item` (confirmed), `update_item` (edited with `before`; moved with from/to bot), `add_proposed` (proposed with examples and run; the 20-limit archives → archived reason `limit`), `add_noticed` (noticed with quote and message; limit archives likewise), `archive_stale_proposed` (archived reason `stale`), `set_template` is a label only: no event.
- `app/memory_settle.py`: `_promote` (settled), `_expire` (archived with its reason) — `by` SETTLE.
- `app/owner_views.py`: `record` (recorded + the old one superseded), `drop` (dropped), `archive` (archived with reason), `restore` (restored), `delete_version` (deleted + `scrub`).
- Callers pass their actor:
  - `app/agent_workflow/tools.py` remember / forget / record_view / drop_view: `memory_events.chat(context.conversation_id, context.turn_id, args.get('_source_message_id'))` (read what `context` carries; the old pipeline's direct card path goes through the same function).
  - `app/agent_chat_stream.py` memory page and views page routes: PAGE.
  - `app/memory_review.py`: `review(run_id)` for `add_proposed` and `archive_stale_proposed`.
  - `app/memory_settle.py`: SETTLE for `_promote`, `_expire` and `owner_views.archive`.
  - `app/role_templates.py`: `template(template_id)` for `add_item` and for the undo's `delete_item`.
  - `app/agent_profile_extract.py`: `extract(message_id)` for its `add_item` calls.
- A test walks `app/` with `ast` and fails when a call to one of the mutating functions (by name, on the modules above) outside its own module passes no `by=` — so a new caller cannot silently log `unknown`.

## Task 3 — the backstage API (`app/backstage_api.py`)

- `GET /backstage/memory?target=&action=&by=&q=&before=&limit=` — owner-only like the other routes (`_owner`), read-only, `MAX_LIMIT` as the others. Rows: `{id, at, target, action, by, text, before, reason, bot, symbol, company, reconstructed, quote, examples, conversation_id, message_id, run, template}` (`bot` = bot name from `_bot_names`, `company` = `owner_views.display_name(symbol)`), `next` cursor. Bad `target`/`action`/`by` → 400.
- `operation_registry`: a GET adds no write; if `tests/test_operation_registry.py` lists backstage routes, keep it passing.

## Task 4 — the tab (frontend)

- `frontend/src/api/backstage.ts`: `listMemoryChanges(filters, before, signal)` and the item type.
- `frontend/src/backstage-view.mjs`: `memoryRow(item, t)` → `{id, time (local), what (对象: 「记忆」 / 「看法 · 公司名（代码）」 / bot name for a bot layer), action label, content (text; an edit: 「旧 → 新」; a deleted or rejected item: 「（已删除，内容不保留）」), by label, basis (quote in 「」, examples count, reason, a link 「查看原对话」 to `#/chat/<conversation_id>` when there is one), reconstructed note 「补记」}`.
- `frontend/src/app/backstage/MemoryTab.tsx` on the pattern of `OperationsTab.tsx` (`usePaged`, `BackstageTable`, `TabState`, `PagedFooter`) plus filters: 对象 (全部 / 记忆 / 看法), 变更 (全部 / 记下 / 推测 / 确认 / 修改 / 归档 / 恢复 / 删除), 谁改的 (全部 / 对话里 / 记忆页 / 每月整理 / 季度沉淀 / 角色模板 / 旧流程提取), and a search box — as the 回答 tab does its filters. Under the table one fixed note: 「标「补记」的是这一栏上线前的变更，按记忆里已有的时间推出来的；那之前的修改和删除没有留下记录。」
- `BackstagePage.tsx` and `routes.mjs`: the sixth tab `memory`, label 「记忆变更」.
- Labels in both locales (`zh-CN.json` list, `en-US.json` map); `npm run -s test:i18n` passes.
- Only the web shows the backstage; no Telegram or WeChat request is added.

## Tests

- `tests/test_memory_events.py` (real PostgreSQL, the test database, as `tests/test_kernel_reconcile.py`'s `stored` fixture does): each profile function writes its event(s) with the right action, `by`, basis and `before`; consequences (topic replaced, cap, limit, stale) carry the cause's `by` and the reason; a duplicate writes nothing; a delete and a rejection scrub earlier events of that item and keep none of its text; view record/supersede/drop/archive/restore/delete; settle's promote/expire; a failure of the change (ProfileError rollback) leaves no event; `backfill` reconstructs each kind once and a second run adds nothing; `page` filters, search, cursor.
- The `ast` caller test (Task 2).
- `tests/test_backstage_api.py`: the route, filters, 400s, owner-only (guest 403), the row shape.
- Frontend node tests: `memoryRow` for each action (edit shows old → new; deleted shows no text; reconstructed note; the conversation link), the tab's filters in the URL/fetch call as the 回答 tab's tests do; i18n.

## Ship

Shadow environment: start it, run the backfill on the shadow copy of the live database, look at the reconstructed history of the owner's real memory in the shadow backstage (`curl` the route with the shadow owner session as the earlier slices did), make a few changes through the shadow API (page add/edit/delete, a chat 「记住」 on the test bot) and see each one in the tab. Report `docs/reports/2026-11-stage-5d2.md`. Full suite on the final commit; ruler; Fable acceptance (a data migration: the new table and its backfill); release with a backup first.
