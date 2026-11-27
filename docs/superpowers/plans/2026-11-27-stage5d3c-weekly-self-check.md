# 5d-3c The weekly self-check: his 不好 answers, sorted by what went wrong

**Goal:** Once a week, the answers the owner marked 不好 that week go to the judge role's model with the question, the answer, his reason and the tools the turn used (and which failed); it puts each in one of 缺数据 / 工具没用对 / 想得太浅 / 记错偏好 / 说得不清楚 / 其他 with one sentence why, and says what to fix first. The report shows in the backstage 质量 tab. A week with none writes an empty report and asks no model.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §10.2 (「每周自检报告。把被点『不好』的回答归类：缺数据、工具选错、想得太浅、记错了你的偏好。每周一份，告诉我们下一步该改哪里」), §9.2 质量.

## Tasks

1. `app/quality_review.py` (new): table `quality_reports`; `gather` (his 不好 verdicts given in the period, at most 40, with question, answer, reason, tools and failed tools; and the good / bad counts), `run(owner, now, last_run_at)` (the calendar's job), `sort_items` (a category outside the list is 其他, a skipped answer 没归类; only an answer that is not JSON fails the run), `recent`.
2. `app/memory_schedule.py`: the job `weekly_quality` every `FINBOT_QUALITY_DAYS` (7) days; a busy month brings forward only the monthly review; its model calls count under the usage purpose `quality`. `app/memory_overview.py`: the memory page's calendar lists the memory jobs only.
3. `GET /backstage/quality` gains `weekly` (the newest 8 reports; null when unreadable) and `weekly_next`; the 质量 tab gains 「每周自检」 at the top; the usage tab names the purpose 每周自检.

Model: the `judge` role (configurable in settings; the server default when unset). Nothing is sent to the owner: the report is the backstage's.

## Tests

`tests/test_quality_review.py` (empty week asks no model; sorting with an unknown category and a skipped answer; not JSON fails and stores nothing; only his and only the period; newest first), `tests/test_memory_schedule.py` (7 days, not brought forward, purpose quality, memory page lists memory jobs only), `tests/test_backstage_api.py` (weekly in the route, unreadable → null), frontend `weeklyReportView` and locales.
