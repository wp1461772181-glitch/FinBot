# 4c Quarterly Settle Implementation Plan — what still holds becomes long-term, what went stale is archived

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every memory item knows when it was last borne out by what the owner said. Once a quarter, aligned with earnings season, the system settles memory: confirmed guesses that kept showing up become long-term, habits and guesses not seen for a long time and views on companies he no longer holds, watches or mentions are archived (kept, dated, restorable), and he gets one short change note. Nothing he said himself as a rule is archived by the system.

**Architecture:** A `last_seen_at` column on profile items, bumped by the monthly review when the model cites fresh evidence for an existing item (each example code-checked exactly like a new proposal) and when a new explicit item repeats an existing one. A second calendar job `quarterly_settle` (`app/memory_settle.py`) in the 4b calendar, due on fixed anchor dates; it is code only (no model call): promote, expire, archive views, post the note. Archived rows carry `archived_at` and a one-line Chinese `archived_reason`.

**Tech Stack:** Python 3, SQLAlchemy (Postgres), pytest; React + TypeScript.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §6.2 (每季沉淀：长期记忆——稳定的东西（你的角色、风格、风险偏好、长期持有的理由）；每季一次，和财报季对齐；从月度画像里挑出持续成立的；过时的归档。会过期：每条记忆带「最近一次被印证」的时间。卖掉的持仓、很久没再出现的习惯，在季度沉淀时归档。新的盖旧的，旧的不删。每月给你一份变更说明。节奏可配置). 复盘 (§6.3) is the next slice (4d) and uses the same job.

## Global Constraints

- **`last_seen_at`** (nullable timestamptz) on `agent_profile_items`, plus `archived_at`, `archived_reason` (≤ 80 chars), `settled_at` (when it became long-term). Additive columns via the existing `ensure_*_column` pattern; existing rows get `last_seen_at = created_at` once at startup (idempotent).
- **Bumped by:** (a) the monthly review: the model may also return `still_seen: [{handle, examples}]` for existing active items (the prompt tells it so in one sentence); each example is checked by the same code as proposals (`_checked`-style: quote in the cited message, his, in window, ≥ 4 chars); ≥ 1 valid example bumps `last_seen_at` to the newest example's date; (b) `profile.add_item` when a new explicit/manual item replaces or duplicates an existing one on the same topic or text. Never bumped by use (`last_used_at` stays what it is).
- **Anchors:** `FINBOT_MEMORY_QUARTER_ANCHORS` default `02-15,05-15,08-15,11-15` (month-day, UTC date, after most earnings releases); the job is due at the first anchor after its last run (first run: the first anchor after registration). Same calendar semantics as 4b (one catch-up run, claims, retry on failure).
- **Promote (long-term):** a confirmed guess (origin `pattern`, status `active`) whose `last_seen_at` is within the last 120 days and which was confirmed at least 60 days ago gets `settled_at`; the block and the page label it 「长期」. Explicit and manual items are his own words and need no promotion (they are already long-term).
- **Expire (archive):** `FINBOT_MEMORY_STALE_DAYS` default 180. Archived with a reason: an active `inferred` (per-turn extractor) or `pattern` item, not settled, whose `last_seen_at` is older than that (「很久没在你的话里出现（最后一次 M月D日）」); a settled item only after twice that. **Never** an explicit or manual item. A **view** (`owner_views`, active) is archived (status `archived`, `ended_at`, reason) when its company is not held now (portfolio ledger), not in the research queue, not a bot's focus company, and not mentioned in his messages for the stale period (「你已不持有、不在关注列表，也很久没提」). Archived means kept and restorable: `POST /agent-chat/profile/{id}/restore` and `POST /agent-chat/views/{id}/restore` (owner only; registry entries as exemptions 「本人在页面上恢复」).
- **The note:** one system-posted message in the default bot's conversation (same marking as 4b), only when something changed: 「这一季的记忆整理：」 + 转为长期 N 条（列出）、归档 M 条（列出，各带原因）+ 「归档的都还在记忆页，可以恢复。」; one channel notice (source `memory`, the same daily cap). Counts from code.
- **No model call** in the settle job. Ledger: nothing. `list_work` shows the job like the monthly one (title 「每季整理记忆」).
- Old engine, guests: unchanged. Tests: files you touch, never the whole suite; check the branch before every commit; WIP-commit before RED.

## Review Focus

1. A confirmed guess seen again last month and confirmed 3 months ago → 长期; one not seen for 200 days → archived with the date; an explicit item untouched for 2 years → untouched.
2. A view on a company he sold last quarter, not in the queue, not mentioned since → archived; the same company still in the research queue → kept.
3. The box is down over 05-15 and comes back on 05-20 → one run on 05-20; next due 08-15.
4. The monthly review returns `still_seen` with a fabricated quote → no bump; a real one → bumped to that message's date.
5. Restoring an archived item puts it back active with `last_seen_at` = now and clears the archive fields.

---

### Task 1: last-seen and the monthly bump (backend)

Files: `app/agent_profile.py` (columns, startup backfill, bump on add), `app/memory_review.py` (`still_seen` parsing and code check, one prompt sentence), tests `tests/test_memory_last_seen.py` (Review Focus 4, the add-bump, backfill idempotent).

### Task 2: the quarterly settle job (backend)

Files: create `app/memory_settle.py` (`run(owner_hash, now, last_run_at) -> dict`), `app/memory_schedule.py` (job `quarterly_settle`, anchor due rule), `app/owner_views.py` (archive + restore), restore routes + registry, block/page label for settled items, `app/work.py` title, tests `tests/test_memory_settle.py` (Review Focus 1–3, 5; the note; nothing changed → no message).

### Task 3: the web

Files: memory page — 「长期」 label on settled items; the archived group shows each item's reason and date and a 「恢复」 button; company page view history shows 已归档 with the reason and 「恢复」 on an archived current view; i18n; tests; screenshots at 1440 and 390.

### Task 4 (controller)

Full suite on the final commit; report; shadow: back-date and run both jobs on real data, read what would be archived; ship under the standing rule (check CI myself — Auto-fix does not report success).
