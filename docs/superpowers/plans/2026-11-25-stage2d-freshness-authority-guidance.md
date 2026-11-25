# 2d Freshness, Authority, Guidance Implementation Plan — the rest of stage 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three things the design asks of stage 2 that 2a–2c did not cover: every read result the model receives says, computed by the system, how fresh its newest item is; every numbered source carries a system-assigned authority rank the model can see; and the latest-quarter section carries the company's own guidance from its earnings release, cited.

**Architecture:** All three are added where the kernel already numbers rows (`app/kernel/toolrun.py`) and where the latest-known block is rendered (`app/latest_known.py`). Freshness and authority are computed by code from fields the rows already carry. Guidance comes from `earnings_history` (written by the earnings reader, whose figures are checked against the release text at extraction) joined to the 8-K row for its source.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §4.11 point 2 (每条资料都带发布时间，工具结果里由系统算好并写明「这批结果里最新的一条是多久以前的」；来源的先后由系统给出：官方备案和公司新闻稿，其次通讯社和主流媒体，其次聚合站，最后才是社交平台和通用网页搜索) and §五 (事实：…指引、最新财报摘要).

## Global Constraints

- Code computes everything; no model call; no new rule the model must remember beyond one true sentence each in the kernel system text describing what the labels mean.
- **Freshness:** for each numbered read result, `meta.newest` (ISO time of the newest dated row) and `meta.newest_age` (Chinese, as 2a writes ages: 「41 分钟前」「3 天前」); dates taken from the fields each source type already has (published_at, filed_at / accepted_at, as_of, period_end for figures — say which field per type); rows with no date do not count; future-stamped rows are ignored for 「最新」 and counted in `meta.future_dated`.
- **Authority:** each citation gets `authority` 1–4 and a Chinese label: 1 官方（SEC 文件、公司新闻稿、交易所公告、系统档案里的数字和由它们算出的数）, 2 通讯社和主流财经媒体 (a short, editable domain list: reuters.com, bloomberg.com, wsj.com, ft.com, cnbc.com, apnews.com, 财新, 第一财经, 证券时报 … — in one module), 3 聚合站和其他新闻 (configured news sources not in tier 2, Yahoo Finance, 金十 …), 4 社交平台和通用网页 (X posts, unknown web domains). The rows shown to the model carry `来源等级: 官方` etc. Nothing is hidden or reordered by it.
- **Guidance:** only figures `earnings_history.guidance` holds (revenue range, gross margin, EPS), for the latest release of the company, cited as `official_filing` with the 8-K's `source_url` (join by accession); labelled 「公司指引（新闻稿）」 with the period it is for if known; omitted if the 8-K row is missing. Every number in the line has its citation (2b's invariant).
- Old engine untouched. Tests: files you touch; never the whole suite. Box is down: local only.

## Review Focus

1. A news search whose newest row is 3 days old says so; a mix with one future-stamped row ignores it and reports it.
2. A web result from reuters.com is tier 2, from an unknown blog tier 4, an X post tier 4, a 10-Q tier 1, a 2b derived figure tier 1.
3. A guidance range where low > high or units disagree is not shown.
4. The block stays within its limits with the guidance line added; it is the first line dropped from the facts section when space is short.

---

### Task 1: freshness and authority on read results

Files: `app/kernel/toolrun.py`, a new `app/source_authority.py`, the kernel system text (two true sentences), tests (`tests/test_kernel_freshness_authority.py`).

### Task 2: guidance in the latest-quarter section

Files: `app/company_facts.py` (a `latest_guidance(symbol)` read joining `earnings_history` to `sec_filing_inventory`), `app/latest_known.py`, tests.

### Task 3 (controller)

Full suite once; report; box-side checks queued (real searches show sensible freshness and tiers; NVDA's guidance line).
