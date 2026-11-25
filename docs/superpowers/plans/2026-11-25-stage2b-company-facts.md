# 2b Company Facts Implementation Plan — the latest numbers of a company, worked out by code at ingestion, carried with their sources

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every company we hold filings for, code keeps the latest quarterly and annual figures, the standard margins, and quarter-over-quarter and year-over-year changes — each figure with its filing, period and basis, each derived number with the two figures it came from. They are refreshed when a filing or press-release figure is stored, and the latest-known block (2a) carries a short 「最新一季」 section built from them, numbered as citations, so 「英伟达最新财报简单说说」 needs no lookup and no `calculate`.

**Architecture:** A new module `app/company_facts.py` reads `sec_filing_inventory.content_financials` (XBRL figures of 10-K/10-Q/20-F, and verified press-release figures of 8-K Exhibit 99.1), picks one value per `(metric, period_end, span)` (a periodic report beats a press release; the newest filing beats an older one), derives 3-month quarters from year-to-date values by subtraction, computes margins and growth, and stores the result in two tables. A refresh runs after a filing's figures are stored, after press-release figures are stored, and in a periodic sweep. `app/latest_known.py` reads the stored facts (no computation at question time).

**Tech Stack:** Python 3, SQLAlchemy, PostgreSQL, pytest.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §五 (档案：事实部分；把核对从回答时挪到入库时；比率和同比环比由代码计算，并记下由哪两个数字算出) and stage 2 of §十二 (「英伟达最新财报简单说说」10 秒内；计算调用次数大幅下降). The 你的看法 / 盯防条件 / 往来 parts of the archive are stages 4 and 5.

## Global Constraints

- **No model call** anywhere in this plan. Everything is deterministic and re-runnable: a refresh of the same inputs gives byte-identical rows.
- **Nothing invented.** A figure exists only if a stored filing states it; a derived figure exists only if both parents exist and their periods fit exactly (same fiscal year, adjacent spans); a ratio only if numerator and denominator share period and span. Units must match (USD with USD); otherwise no row.
- **Provenance on every row.** A stated figure carries `accession_number`, `form`, `filed_at`, `source_url`, `concept`, `basis` (`reported` or `press_release_unaudited`). A derived row carries `formula` (e.g. `ytd9 - ytd6`, `gross_profit / revenue`, `(a - b) / b`) and the ids of its parents.
- **Checks at ingestion, not at answer time.** Where the data allows a consistency check (gross profit = revenue − cost of revenue within 0.5 %; a derived quarter is not negative for revenue), a failed check marks the rows `check_failed` with a reason; they are kept for inspection and never shown to the model as facts.
- **Do not change** `query_financials`, `calculate`, `release_figures` extraction, or the XBRL fetch. Hooks are additive and never make a fetch or store fail: a refresh error is logged once and swallowed.
- The latest-known block keeps its limits (≤ 2,000 characters in all; each line ≤ 160); the facts section is at most 6 lines per company and is dropped first when the block would be too long.
- Tests: the files you touch, never the whole suite. Reuse `tests/sw1_filings.py` fixtures (`seed`, `figure`, `nvda_filings`, …). Commit with a plain-English message, files by name.

## Review Focus

1. A 10-Q that reports cash flow only as 9-month YTD: the quarter is derived from YTD9 − YTD6 of the same fiscal year; a missing YTD6 means no quarter row (never YTD9 shown as a quarter).
2. Q4: derived as FY − YTD9 only when both come from the same fiscal year's filings; a 52/53-week year or a fiscal-year-end change (period ends not lining up within 7 days) gives no Q4.
3. A restatement: a later 10-K restating last year's revenue replaces the earlier value, and every derived row that used it is recomputed.
4. A press release figure for a quarter whose 10-Q is not yet filed is shown with 「新闻稿，未经审计」; once the 10-Q is stored the release figure is superseded on the next refresh.
5. NVIDIA's fiscal year (ends late January): fiscal labels come from the filing's own period dates and fiscal year end, not the calendar.

---

### Task 1: `app/company_facts.py` and its tables

**Interfaces — produces:**
- Table `company_facts`: `id`, `symbol`, `metric` (the 10 metrics `query_financials` knows), `period_start` (nullable), `period_end`, `span` (`quarter`, `ytd6`, `ytd9`, `annual`, `instant`), `fiscal_year`, `fiscal_period` (`Q1`–`Q4`, `FY`), `value` (numeric), `unit`, `kind` (`stated` or `derived`), `basis` (`reported`, `press_release_unaudited`, or for derived rows the weakest basis of its parents), `accession_number`, `form`, `filed_at`, `source_url`, `concept` (stated rows), `formula` and `parents` (JSON list of fact ids; derived rows), `status` (`ok` or `check_failed`), `reason`, `built_at`. Unique on `(symbol, metric, period_end, span)`.
- Table `company_ratios`: `id`, `symbol`, `name` (`gross_margin`, `operating_margin`, `net_margin`, `fcf` only if capex exists — it does not today, so leave it out; `revenue_qoq`, `revenue_yoy`, `net_income_qoq`, `net_income_yoy`, `gross_margin_change_qoq_pp`, `gross_margin_change_yoy_pp`), `period_end`, `span`, `fiscal_year`, `fiscal_period`, `value` (a fraction, or percentage points for `_pp`), `formula`, `parents` (fact ids or ratio ids), `basis`, `status`, `reason`, `built_at`. Unique on `(symbol, name, period_end, span)`.
- `def refresh(symbol: str, *, db=None) -> dict` — rebuilds both tables for one symbol in one transaction (delete-then-insert of that symbol's rows, or upsert — your choice, but the result is identical either way); returns counts and any check failures.
- `def refresh_all(*, limit: int | None = None) -> dict` — every symbol with figures.
- `def latest_quarter(symbol: str, *, db=None) -> dict | None` — the newest quarter that has at least revenue: its fiscal label, period end, basis, and the facts and ratios of that quarter plus the comparison periods used, each with its id, value, unit, provenance and formula.
- Period logic reuses `app/agent_workflow/financials.py` (`period_label`, `_SPANS`, `_MONTH_SPANS`) rather than reimplementing it.

- [ ] **Step 1: failing tests** (`tests/test_company_facts.py`, real PostgreSQL via `tests/sw1_filings.py`): every Review Focus case; a stated quarter from a 10-Q; margins of a quarter; QoQ and YoY with their parents; a periodic report beating a press release for the same period, and a press release kept when no report exists; an inconsistent gross profit → `check_failed`; units mismatch → no ratio; idempotence (refresh twice → identical rows); a symbol with no figures → no rows, no error; `latest_quarter` for NVDA from `nvda_filings` matches hand-computed values.
- [ ] **Steps 2–5:** see them fail, implement, run the new file and `tests/test_agent_financials.py`, commit.

### Task 2: refresh hooks and the latest-known facts section

**Files:** `app/sec_filings.py` (after `content_financials` is set in `fetch_inventory_content`), `app/release_figures.py` (after `_store`), `app/background.py` (a sweep: `refresh_all` every 6 hours and once at startup), `app/latest_known.py` (the facts section), tests.

- Hooks call `company_facts.refresh(symbol)` after the surrounding commit, in a way that cannot fail the caller and does not hold the caller's transaction open.
- The facts section, under each company in the block, from `latest_quarter` only (no computation at question time): 「最新一季：FY2027 Q3（截至 2026-10-25，新闻稿未经审计）」 then up to 5 lines such as 「营收 1,158.44 亿美元 [n]，环比 +20.4%（由 [n] 和 [m] 算出），同比 +…」, 「毛利率 74.8%（毛利 [k] ÷ 营收 [n]）」, 「净利润 … [p]」, 「经营现金流 …（单季，由九个月累计减六个月累计算出）[q]」. Every stated figure is numbered as a citation through the same path 2a's block lines use (`official_filing` with the filing's `source_url`); every derived figure is numbered as a citation of type `calculation` with `derived: true` and its `parents` pointing at the citation numbers of its inputs — the same shape the `calculate` tool produces, so the answer can cite it directly.
- Money in 亿美元 with two decimals for values ≥ 1 亿, otherwise 万美元; percentages with one decimal; signs always shown for changes.
- `check_failed` rows are never shown.

- [ ] **Step 1: failing tests:** a hook failure does not fail `fetch_inventory_content` or `_store`; a stored 10-Q triggers a refresh of that symbol; the block for NVDA (fixtures) contains the facts section with numbered stated and derived citations whose parents resolve; a company with figures but no quarter with revenue gets no section; the section is dropped first under the length limit; the block text never contains a number that is not in the citations (assert by parsing).
- [ ] **Steps 2–5** as Task 1; run `tests/test_latest_known.py`, `tests/test_company_facts.py`, `tests/test_kernel_*.py`, `tests/test_sec_filings.py`, `tests/test_release_figures.py`.

### Task 3 (controller)

Full suite once locally. Box-side checks wait for the box (backlog §二十四补充): refresh_all on the shadow database (timing, row counts, any `check_failed` and why), the NVDA block, 「英伟达最新财报简单说说」 timed (target ≤ 10 s, tool calls 0–1, no `calculate`), ruler once. Report.
