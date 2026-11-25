# 2c Archive On Demand Implementation Plan — a company the owner asks about gets an archive, and keeps it

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Who has an archive is decided by the owner's life, not a fixed list: his holdings, his research queue, and any US-listed company he asks about. When he asks about one we hold nothing for, the system starts fetching its recent filings from SEC at once (no model, no card), tells the model so in the latest-known block, and from then on keeps it updated like the others.

**Architecture:** A table `archive_subjects` lists the companies to keep, with why. A small worker builds a new subject: SEC filing discovery for the symbol, content and XBRL for the filings that matter (the latest 10-K, the 10-Qs and earnings-release 8-Ks of the last 15 months), then `company_facts.refresh`. The hourly SEC monitor's symbol set includes all subjects. `app/latest_known.py` recognises a valid US ticker the owner names even when we hold nothing for it, enqueues a build, and writes one true line about it.

**Tech Stack:** Python 3, SQLAlchemy, PostgreSQL, pytest. SEC access through the existing `SecEdgarProvider`.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §五 (「你问到一家还没有档案的公司，它现场拉取、整理、回答，顺手存下，下次直接答」; 「谁有档案：你的持仓、研究队列、问过的公司」).

## Global Constraints

- **No model call; no card.** Fetching public filings is a read of public data on the owner's behalf; it costs no money. It is triggered only by the owner (never a guest) and only for a symbol that SEC's own ticker list knows.
- **Bounded.** One build at a time; at most 20 waiting; at most 30 builds per hour in all; a symbol is not rebuilt within 6 hours of a successful build or within 1 hour of a failed one. Each build has a wall clock of 5 minutes and SEC's own rate limit is respected through the provider (read how `SecEdgarProvider` throttles and identifies itself; do not change it).
- **True words only.** The line for a company being built says what is happening and nothing more: 「系统里还没有 X 的资料：已开始从 SEC 取最近的年报、季报和财报新闻稿，通常一两分钟；这一轮请用工具查，或稍后再问。」 A failed build says so on the next mention: 「上次从 SEC 取 X 的资料没有成功（原因），这一轮请用工具查。」
- **The monitor stays bounded:** `MAX_ACTIVE_SYMBOLS` becomes configurable (`FINBOT_ACTIVE_SYMBOLS_MAX`, default 80); subjects come after the defaults, ordered held → queue → most recently asked.
- **Existing behaviour unchanged** for companies we already hold: no new fetch is triggered for them by a mention.
- Tests mock SEC (no network). Run the files you touch, never the whole suite. Commit with a plain-English message, files by name. The production box is down: local database only.

## Review Focus

1. A guest message naming $XYZ: no build, no subject row.
2. A message with a ticker-looking word that SEC does not know (`$ABCDE`, `IT`, `CEO`): no build.
3. A burst: the owner names 25 new tickers in one message — 3 get sections in the block (2a's limit), at most 20 builds are queued, the rest named in the 「另提到」 line; the hourly cap holds across messages.
4. SEC returns 403/429 or times out mid-build: the build is marked failed with a short reason, partial rows already stored stay (they are real filings), and the next mention says the truth.
5. The owner sells a holding or removes a queue symbol: the subject's reason updates; a subject nobody holds, queues or asked about in 90 days stops being monitored (row kept with `retired_at`), its stored filings stay.

---

### Task 1: subjects, the build worker and the monitor set

**Interfaces — produces:**
- Table `archive_subjects`: `symbol` (PK), `held` (bool), `queued` (bool), `asked_at` (nullable), `first_seen_at`, `build_status` (`never`, `queued`, `building`, `ok`, `failed`), `build_started_at`, `build_finished_at`, `build_error` (short code ≤ 64), `filings_added` (int), `retired_at` (nullable).
- `app/archive_subjects.py`:
  - `def sec_symbol(value: str) -> str | None` — the normalised symbol if SEC's ticker list has it (the list cached for 24 h through the provider; a fetch failure keeps the previous list).
  - `def sync_owner_subjects(owner_hash: str) -> dict` — sets `held` / `queued` from holdings (`app/portfolio.py::build_summary` or the transactions table) and the research queue (`agent_research_queue`); sets `retired_at` per Review Focus 5.
  - `def note_asked(symbol: str) -> str` — records the ask and returns the subject's state for the block (`ok`, `building`, `queued`, `failed:<reason>`, `limited`).
  - `async def enqueue_build(symbol: str) -> bool` and a worker started with the API (one at a time, the caps above) running `build(symbol)`.
  - `def build(symbol: str) -> dict` — `scan_sec_filings`, then `fetch_inventory_content` for the filings that matter (see Architecture), then `company_facts.refresh`; returns counts; never raises out of the worker.
  - `app/active_symbols.py::active_symbols` includes non-retired subjects after the defaults, cap configurable.
  - The 6-hour sweep from 2b also runs `sync_owner_subjects` for the owner.
- [ ] **Step 1: failing tests** (`tests/test_archive_subjects.py`, a fake provider): each Review Focus case that does not involve the block; build order and which filings are fetched; caps; failed build; retire after 90 days; `active_symbols` order and cap. **Steps 2–5:** see them fail, implement, run the new file plus `tests/test_sec_filings.py`, `tests/test_company_facts.py`, `tests/test_active_symbols*.py` (if any), commit.

### Task 2: the latest-known block asks for builds

**Files:** `app/latest_known.py`, tests.

- For the owner's turn only: a cashtag or bare ticker that `sec_symbol` accepts but `known` lacks counts as a mention; `note_asked` is called for every mentioned symbol (known ones too, so the asked date stays fresh); an unknown one gets `enqueue_build` and the line from Global Constraints instead of a section; a failed one gets the failure line.
- A company name from `company_directory` whose symbol we hold nothing for is treated the same way.
- All of this stays inside the block's existing budget; `sec_symbol` is never a network call inside a turn (cache only; a cold cache means the unknown ticker is ignored this turn and the cache is warmed in the background).
- [ ] **Step 1: failing tests:** Review Focus 1–3 through the block; the line wording; a known symbol mentioned only refreshes `asked_at`; a guest's turn changes nothing in `archive_subjects`. **Steps 2–5** as Task 1; run `tests/test_latest_known.py`, `tests/test_archive_subjects.py`, `tests/test_kernel_*.py`.

### Task 3 (controller)

Full suite once locally. Box-side (after 2a and 2b): ask about a company not in the database, watch the build (time, filings added, facts built), ask again; check the monitor picks it up; report.
