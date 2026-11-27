# 5d-3b The backstage 「质量」 tab: the answers he marked 不好, and the ruler's history

**Goal:** The seventh backstage tab, 「质量」: how his 「好／不好」 runs week by week, the answers he marked 不好 with his reason (each opens the answer's course, as in 回答), and every ruler run on the box with its pass rate, times and failed cases. The weekly self-check's classification (§10.2) joins it in 5d-3c. Read-only.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §9.2 (「质量：被点『不好』的回答、每周自检的归类、尺子的历次成绩」), §10.1, §10.2.

## Task 1 — the ruler writes what a run was (`ruler/run.py`)

- `run` writes `meta.json` next to `summary.json`: `{"started_at", "finished_at" (UTC ISO), "suite" (the path as given), "cases" (how many the suite had after `--cases`), "base", "model", "parallel", "note"}`; a new optional `--note` (free text; the release notes put the commit there).
- Nothing else in the run changes.

## Task 2 — the API (`app/backstage_api.py`, `GET /backstage/quality`)

- Owner-only, read-only, like the other routes.
- `feedback`: the last 8 weeks (Monday-based, Beijing time) of his verdicts by the answer's week: `[{week_start, good, bad}]`, newest first, weeks with none included as zeros; and `bad`: the newest 20 answers he marked 不好: `{message_id, at (answer time), rated_at, bot, question, reason, channel}`.
- `ruler`: the runs under `FINBOT_RULER_OUT` (default `/opt/finbot/ruler-out`): every directory directly in it that holds a `summary.json`, newest first by `meta.finished_at` or else the summary's modification time, at most 50: `{name, at, suite, note, turns, pass_rate, total_ms_p50, total_ms_p90, model_calls_mean, failed: [{case_id, turn, checks}] (from results.jsonl, at most 20), meta: bool}`. A directory that cannot be read is skipped and named in `ruler_errors`; a missing root is an empty list. No path outside the root is read (names are the root's direct children; symlinks are not followed).

## Task 3 — the tab (frontend)

- `frontend/src/app/backstage/QualityTab.tsx`, tab `quality` 「质量」 in `BackstagePage.tsx` and `routes.mjs`.
- 「你的评价」: the weeks as a small table (周 / 好 / 不好), then 「被点不好的回答」 (时间 / bot / 问题 / 原因), a row opens `AnswerDrawer`.
- 「尺子历次成绩」: 时间 / 名称 / 题数 / 通过率 / 中位数 / P90 / 没过的题 (ids); a run without `meta.json` says 「（早期记录，没有题库说明）」 under its name; the note line shows when there is one.
- Row helpers in `backstage-view.mjs` with tests; locales.

## Tests

- `tests/test_backstage_quality.py`: owner-only; the weeks (zeros, Beijing week boundary, only his); the bad list (reason, question, bot, newest first, at most 20); ruler runs from a temp root (with and without meta, unreadable summary skipped and named, a file and a symlink at the root ignored, newest first, failed cases from results.jsonl, the 50 cap).
- `tests/test_ruler_run.py`: `meta.json` written with the note.
- Frontend: the row helpers, the route, locales.

## Ship

Normal tier: full suite on the final commit, ruler (with `--note`, so the tab shows the first run with meta), shadow check of the API on the box's real ruler directory (the shadow API reads the same root), review, release.
