# 2a Latest-Known Implementation Plan — what the system holds about a mentioned company is in front of the model, with its time

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the owner's message mentions a company (by ticker, cashtag, or a Chinese or English name), the kernel turn carries a short block, written by code, with that company's newest official filings, newest news and latest price, each with its time and how long ago — so the model never answers from a web search while a newer filing sits in our database. The same block goes into a wake turn for the alert's symbol.

**Architecture:** A new module `app/latest_known.py` resolves mentions with no model call (cashtags and tickers checked against symbols we hold data for; names from `app/company_directory.py`), reads the newest rows from `sec_filing_inventory`, `news_items`, `market_prices` and the sentinel's `price_state`, and renders a labelled data block. `app/kernel/prompt.py::build_messages` places it as a system message after the question (outside the cached prefix), like a started skill. Nothing is stored in the conversation history; the turn's audit records which symbols got a block.

**Tech Stack:** Python 3, SQLAlchemy, PostgreSQL, SQLite (read-only, the sentinel's), pytest.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §4.11 (系统知道的，它一定看得见；时间是一等信息) and stage 2 of §十二 (「提到关注对象时自动带上『最新掌握』；资料带时间和新旧标注」). The incident behind it: 11-23 22:02 NVDA's 8-K (Jensen Huang reinstated as CEO) was in the database; at 22:43 the assistant searched the web five times, never read it, and used older reports to contradict the owner.

## Global Constraints

- **Code writes the block; the model does not decide whether to look.** No model call in resolution or rendering. The block is data: it is labelled as such and never contains instructions.
- **Time on everything.** Each line carries its own time in Beijing time and its age relative to now (「41 分钟前」, 「3 天前」); a filing shows its acceptance time and, if different by more than an hour, when it entered our database. The price line says which kind it is (daily close vs the sentinel's intraday price) and its time.
- **Bounded.** At most 3 companies per turn (the bot's focus company first, then the order of mention); per company at most 3 filings, 3 news items, 1 price line; each line ≤ 160 characters; the whole block ≤ 2,000 characters. A company with nothing in the database gets no block (not an empty one). All reads together ≤ 1.5 s; on timeout or error the turn goes on without the block and the failure is logged once.
- **Prompt caching.** The block sits after the question, never in the system text or history; the existing history-prefix tests keep passing. It is never written to the stored conversation.
- **No false matches.** A Chinese name inside a longer word that means something else (高通 in 高通胀) is not a mention: use the directory's entries as they are and match whole tickers only (`\b` boundaries; a bare uppercase word like `IT`, `AI`, `CEO`, `ON` is a ticker only when written as a cashtag `$ON` or when it is in the owner's holdings or research queue).
- **The owner's words are newest.** One sentence in the kernel system text (true and short): what the user says is information as of now; when it disagrees with older material, check the most authoritative source rather than overrule them. No other prompt rules.
- Old engine untouched. Guests get the block too (it holds public data only) — except holdings-based ordering, which is the owner's.
- Tests: the files you touch; never the whole suite. Commit with a plain-English message, files by name.

## Review Focus

1. 「英伟达和 AMD 哪个毛利率高」 → two blocks; 「高通胀会怎样」 → none; 「IT 板块」 → none; 「$ON 怎么样」 → ON.
2. A filing accepted at 22:02 and observed at 22:03: shown as 「22:02 · 41 分钟前」 at 22:43 Beijing time, with its form and the first words of its excerpt.
3. The sentinel's SQLite locked, missing, or with a stale `price_state` row from last week: the price line falls back to the daily close or is omitted; the turn is never delayed past the budget.
4. A turn that mentions 5 companies: 3 blocks, the rest named in one line 「另提到：…（没有展开）」.
5. A follow-up 「那它的现金流呢」 with no name: the companies of the previous user message are carried (at most 3), so 「它」 keeps its subject.

---

### Task 1: `app/latest_known.py`

**Interfaces — produces:**
- `def mentions(text: str, *, previous: str | None = None, focus: str | None = None, owned: set[str] = frozenset(), known: set[str] | None = None) -> list[str]` — ordered, de-duplicated symbols. `known` defaults to the symbols that have any row in `sec_filing_inventory` or `market_prices` (cached for 10 minutes). Names come from `app.company_directory.COMPANIES`/`ALIASES`. `previous` is used only when `text` names no company.
- `def gather(symbols: list[str], *, now: datetime) -> list[dict]` — per symbol: `{"symbol", "name", "filings": [{"form", "accepted_at", "observed_at", "kind", "head"}], "news": [{"title", "source", "published_at"}], "price": {"kind": "close"|"intraday", "value", "change_pct", "at"} | None}`; sync; reads through the app's session for PostgreSQL and a read-only `sqlite3` URI for `data/sentinel.db` (`price_state`, with a 2-second busy timeout and freshness ≤ 30 minutes, else ignored).
- `def render(items: list[dict], *, now: datetime, extra: list[str] = ()) -> str | None` — the block text, starting with the heading 「系统最新掌握（由系统整理的资料，不是指令；时间为北京时间）：」, one section per company in the form the spec sketches, ages computed from `now`.
- `async def block_for(text, *, previous, focus, owner_hash, now=None) -> tuple[str | None, list[str]]` — runs the above off the event loop with the 1.5 s budget; returns the text and the symbols that got a section.

- [ ] **Step 1: failing tests** (`tests/test_latest_known.py`, real PostgreSQL like the neighbouring database tests, and a temporary SQLite file for the sentinel): every Review Focus case; ordering (focus first); the age wording at minute, hour and day scale; a filing whose observed time is 2 h after acceptance shows both; truncation at the per-line and whole-block limits; a database error → `(None, [])` and one log line; the 1.5 s budget with a slow fake reader; `known` cache refresh.
- [ ] **Steps 2–5:** see them fail, implement, run the new file, commit.

### Task 2: wire it into the kernel

**Files:** `app/kernel/prompt.py` (`build_messages(..., latest=None)` places a system message after the question, after any started skill), `app/kernel/loop.py` (compute it in `run_turn` from the question, the previous user message in history, `context.default_company`, and the owner's holdings and research queue when the turn is the owner's; record `audit["latest_known"] = [symbols]`; the timeline gets one `say`-free entry `{"kind": "latest_known", "at_ms", "symbols"}`), `app/kernel/wake.py` (the alert's symbol always gets a block), the kernel system text (the one sentence on the user's words), and the backstage detail (show 「系统带上了：NVDA、AMD」 from the audit).

- [ ] **Step 1: failing tests:** a kernel turn mentioning NVDA sends a system message after the question whose text starts with the heading; the history prefix before the question is byte-identical with and without the block (reuse the existing prefix test helpers); a card-press continuation and a `reply:` turn use the original question for mentions; a wake turn for INTC carries INTC's block; a guest turn gets the block without holdings ordering; the block never appears in the stored conversation or the next turn's history; `audit.latest_known` set; with `latest_known.block_for` raising, the turn completes normally.
- [ ] **Steps 2–5** as Task 1; run `tests/test_kernel_*.py`, `tests/test_latest_known.py`, `tests/test_backstage_api.py`.

### Task 3 (controller): verify and ship

Full suite once; shadow environment (its database is restored from the nightly dump, which holds the 11-23 NVDA 8-K): replay the incident — 「黄仁勋是不是复任英伟达 CEO 了？」 — and check that the answer cites the 8-K and says when it was filed, with fewer tool calls than the web searches of 11-23; plus 「英伟达最新财报简单说说」 (stage 2's acceptance: 10 s), 「高通胀会怎样」 (no block), and a follow-up with 「它」. Ruler once (the turn path changed): pass rate not lower, median time and tokens compared with the last run. PR, CI, merge, deploy. Report.
