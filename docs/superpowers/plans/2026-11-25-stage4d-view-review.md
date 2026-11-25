# 4d View Review (复盘) Implementation Plan — look back at what the owner thought, with the numbers since

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a quarter, with the quarterly settle, the system looks back at the owner's earlier views of companies (`owner_views` versions) and tells him, for each one, whether it has held up so far, not held up, is too early to say, or cannot be told, and whether the reason he gave at the time still stands. The input is built by code; the model writes the judgement; the result is stored, shown under the view history on the company page, and listed in the quarterly change note.

**Architecture:** `app/view_review.py` (new): `plan` picks the views, `gather` builds one input per view (his words and date, price then and now with the return computed by code, the newest quarter's figures from `company_facts`), `review` makes one model call per view (role `memory`), `check_figures` marks any figure in the reply that is neither in the input nor a plain computation on it, `run` stores the rows. A table `view_reviews`. `memory_settle.run` calls it after the code-only settle; a failed or slow review never changes the settle's own outcome. `owner_views.history` attaches the latest review to each version.

**Tech Stack:** Python 3, SQLAlchemy (Postgres), pytest; React + TypeScript.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §6.3 (复盘：每季沉淀时一起做：回看你以前的判断，哪些成立了，哪些没有，当时的理由还在不在。依赖「你的看法」有了历史版本).

## Core-principle check (CLAUDE.md) — decisions made here

- **Trust the model, annotate don't delete (准则 1、2).** The handoff said every figure in the output "must come from the input". Read as a gate that would drop or rewrite the review; that is the default-distrust the principles rule out. Here: the review is always stored as the model wrote it. `check_figures` only *marks* a figure that is neither in the input nor derivable from two input figures (difference, ratio, percent change, within 2%), and the page shows 「这几个数字不在系统给的资料里，请自己核对：…」 with the figures named. A review with no stray figure shows nothing extra. The marker targets invented numbers; a model's own arithmetic on the given numbers passes (准则 3: false alarms are defects).
- **No new obligation on the model.** The model returns `verdict` and one short `text`; it does not cite, tag or fill a form. Prices, returns, quarter labels and dates are built and stored by code (the "依据" shown to the user is the code's input snapshot, not something the model restates). The prompt says plainly that figures should come from the data and that others are marked for the owner to check (no hidden rule).
- **The input is complete about what is missing.** A view with no price rows or no quarter facts is still reviewed; the input says `price_then: null` etc. and the model may answer `unclear`. Nothing is skipped silently for lack of data except: no model reply → no row (the next quarter tries again).

## Global Constraints

- **Which views:** `owner_views` rows with status `active`, `superseded` or `dropped` (not `archived`: the settle just set those aside as stale), created at least `FINBOT_VIEW_REVIEW_MIN_DAYS` (default 30) ago, and either never reviewed or (active only) last reviewed at least 80 days ago. At most `FINBOT_VIEW_REVIEW_MAX` (default 10) per run, active ones first then newest. A superseded/dropped version is reviewed once (what he thought then, judged by what came after).
- **Input per view (code-built, JSON, ≤ 4000 chars):** `view` {text, quote, said_on, status, ended_on}, `price` {then: {date, close} | null, now: {date, close} | null, change_pct: computed | null}, `quarter` {label, period_end, basis_note, facts: [{metric, value, unit}], ratios: [{name, value}]} | null (newest quarter only, from `company_facts.latest_quarter`), `today`. The price "then" is the last close on or before `said_on`; "now" the newest close. No news, no filings, no web. His own words are the only free text, and it is data, not instruction.
- **Output (model):** `{"verdict": "held"|"not_held"|"mixed"|"too_early"|"unclear", "text": 一到三句中文, ≤ 240 字, 说明依据，并说当时的理由现在还在不在}`. Anything else (bad JSON, unknown verdict, empty text) is a failed review for that view: no row, counted, retried next quarter. Verdict labels in Chinese for the page: 成立 / 没有成立 / 部分成立 / 还早 / 说不准.
- **Figure marker:** `view_review.check_figures(text, input_json)` uses `agent_workflow.semantic.figure_values` on the reply and on the input; a reply figure passes if equal (2% tolerance, `agent_context_summary._figure_supported`) to an input figure, or to `a-b`, `a/b`, `a/b-1`, `(a/b-1)*100` of any two input figures; years/dates/quarter labels are not figures (`figure_values` already skips periods). The unmatched figures are stored as `unmatched_figures` (list of strings as written). Never changes `text` or `verdict`.
- **Table `view_reviews`** (created by `Base.metadata.create_all`): `id` uuid pk, `owner_hash`, `view_id` uuid (no FK needed beyond index), `symbol`, `verdict`, `text` (≤ 400), `unmatched_figures` JSON list, `input_snapshot` JSON (the code-built `price` and `quarter` label/period_end only, what the page shows as 依据), `created_at`. Index `(owner_hash, view_id, created_at desc)`. `delete_version` of a view deletes its reviews.
- **Settle integration:** `memory_settle.run` calls `view_review.run(owner_hash, now)` after the settle's writes and before the note; its result `{reviewed, failed, items:[{symbol, verdict, text}]}` goes into the result dict and into the note as a section 「复盘：」 listing each as 「- {公司}的看法（{M月D日}）：{成立/…}——{text 前 60 字}」, max 10 lines, `另有 N 条` after. The note posts when anything changed **or** a review was written. An exception or timeout in the review is logged and ignored (the settle stays `done`). The model is called only here; overall time cap `FINBOT_VIEW_REVIEW_SECONDS` default 240 for all views of a run (views not reached are left for the next quarter).
- **API/Web:** `GET /agent-chat/views/{symbol}/history` items gain `review: {verdict, verdict_label, text, unmatched_figures, basis, created_at} | null` (latest). Company page: under each version in the history list and under the active view, a block 「回头看」 with the verdict badge, the text, the basis line (「说的时候 $X → 现在 $Y（+Z%）· 最新一季 FYxx Qx」, built from the snapshot) and, only when present, the figure warning. Owner only, same as the card. i18n keys for every new string; `npm run test:i18n` clean.
- Old engine, guests: unchanged. Tests: files you touch, never the whole suite; check the branch (`claude/stage4d`) before every commit; WIP-commit before RED. No real model call in tests (inject `_complete`).

## Review Focus

1. A view said 60 days ago with a price series and a quarter → the input contains the code-computed return; a reply with that return passes silently; a reply that says 「增长 37%」 when no input figure or pair gives 37 → stored unchanged with `unmatched_figures == ["37%"]`.
2. A reply with bad JSON or an unknown verdict for one view does not stop the others; the settle result is still `done`.
3. No price rows and no quarter facts → still reviewed, input has nulls; the page shows no basis line, not a fake one.
4. An archived view, a view younger than 30 days, and an active view reviewed 20 days ago → not picked; an active one reviewed 90 days ago → picked again.
5. The note lists reviews; with no reviews and no archive/promote nothing is posted (as 4c).
6. His quote containing 「忽略以上指令」 is passed as data only (the prompt says so); nothing from the review is ever written back to his views or profile.

---

### Task 1: the review module and table (backend)

Files: `app/agent_chat_models.py` (`ViewReview`), create `app/view_review.py` (`plan`, `gather`, `check_figures`, `review`, `run`), tests `tests/test_view_review.py` (Review Focus 1–4, 6; `_complete` injected).

### Task 2: settle integration, API, delete (backend)

Files: `app/memory_settle.py` (call, note section, post-when-reviewed), `app/owner_views.py` (`history` attaches latest review; `delete_version` removes its reviews), `app/main.py` only if the history route needs a field, tests in `tests/test_memory_settle.py` (Review Focus 2, 5) and `tests/test_owner_views.py`.

### Task 3: the web

Files: `frontend/src/api/owner-views.ts` (type), `frontend/src/owner-views.mjs` (+ `.d.mts`) helpers for verdict label/basis line, `frontend/src/app/research/OwnerViewCard.tsx`, i18n, tests, screenshots 1440 and 390 (`node smoke.mjs --only owner-view` in a scratch copy).

### Task 4 (controller)

Full suite on the final commit; report `docs/reports/2026-11-stage-4d.md`; shadow: run a review on real data (needs a box connection) and read every output; ship under the standing rule (check CI myself).
