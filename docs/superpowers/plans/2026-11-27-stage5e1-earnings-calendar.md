# 5e-1 The earnings calendar and consensus

**Goal:** The system knows, for every company the owner holds, queues or has a bot focus on, when it reports next (and before / after the market) and what analysts expect (EPS and revenue), with where that came from and when it was read; the kernel sees it in 「系统最新掌握」. This is the data the evening-before preparation (5e-2) and the actual-vs-expected line of the earnings follow-up (5e-3) use.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §7.4, §5 (一致预期排第一). Provider decided with the owner on 11-27: Finnhub's free plan (`/calendar/earnings`); the owner placed `FINNHUB_API_KEY` on the box himself.

## Tasks

1. `app/earnings_calendar.py` + table `earnings_calendar` (one row per symbol and fiscal quarter and source): `parse`, `finnhub_fetch` (the provider: another one is another function returning the same rows), `tracked_symbols`, `store` (upsert; a moved date updates the row), `refresh` (when the last fetch is older than 20 h; no key → nothing; one company failing does not stop the others; 1.1 s between calls for the free plan's 60 a minute), `upcoming`, `line` (date with the weekday written by code, before / after, fiscal quarter, consensus with 「Finnhub，调整后口径」 and the time read).
2. A background loop `earnings-calendar` every 6 h.
3. `app/latest_known.py`: each company's section gains the 「财报日历」 line as a citable row (source Finnhub); a company with only a calendar row still gets a section.

## Tests

`tests/test_earnings_calendar.py`: parse, the key only in the query, refresh (store, fresh skip, moved date, a failing company, rows of another symbol dropped), no key, upcoming and the line, the latest-known section with its citation; the loop's interval.
