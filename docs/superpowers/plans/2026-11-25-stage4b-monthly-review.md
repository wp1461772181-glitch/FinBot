# 4b Monthly Review Implementation Plan — scheduled memory jobs and "what I think I've learned about you"

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a month (or sooner when enough new conversation has piled up), the assistant reads back what the owner said since the last review, writes down the habits and current interests he never stated but that keep showing up — each with a few of his own sentences as examples and marked 「我的推测」 — uses them only lightly, and asks him in one message whether they are right. What he confirms becomes ordinary memory; what he rejects is gone. Underneath: a small calendar for memory jobs that remembers when each last ran, so a restart neither reruns nor skips one.

**Architecture:** A table `memory_jobs` (job name, owner, last run, last outcome, next due) and a module `app/memory_schedule.py` with `due(now)`, `claim(job)` (row lock / advisory lock so two workers never run one job twice) and `finish(job, outcome)`; one background loop `memory-jobs` (every 10 minutes) runs whatever is due. The monthly job lives in `app/memory_review.py`: it collects the owner's own messages since the last review, makes one model call, checks every example against the stored messages in code, stores the survivors as profile items with origin `pattern` and status `proposed`, and posts one message (and a channel notice) asking him to confirm.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy (Postgres), asyncio background loops, pytest; React + TypeScript.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §6.2 (每月整理：画像——你没明说但反复出现的习惯（总是先看同比、常在周一早上问持仓）；近期关注的方向；每月一次，或新对话攒够一定数量时，先到为准；它从这段时间的对话里归纳，每条附上几次例子，标为「我的推测」。明说的和推测的分开…它推测的先轻用（影响回答的详略和顺序，不影响结论），并在每月整理后告诉你「这个月我对你的了解多了这几条，对吗」，你确认后才算正式记忆。每月给你一份变更说明。节奏可配置), §十四 point 8 (memory cadence is configurable; extra model calls go into the usage ledger).

## Global Constraints

- **Cadence (env, defaults):** `FINBOT_MEMORY_REVIEW_DAYS=30`; `FINBOT_MEMORY_REVIEW_MIN_MESSAGES=40` owner messages since the last review triggers it early; it never runs with fewer than `FINBOT_MEMORY_REVIEW_FLOOR=10` owner messages (then it records `skipped: too_few` and waits for the next due time). First run: due 30 days after the job row is created, or earlier by the message rule. `memory-jobs` runs only where `BACKGROUND_LOOPS` is on (never in the shadow).
- **Calendar semantics:** a job that was due while the box was down runs once at the next tick (no catch-up of several missed runs); a restart in the middle leaves the claim to expire after 30 minutes and the job runs again at the next tick; two API workers never run the same job (DB lock, test it). Outcomes `done | skipped | failed` with a one-sentence Chinese reason.
- **Model:** a new model role `memory` (`agent_model_roles.ROLES`, settings row 「记忆整理」: 「每月整理你的习惯和关注用哪个模型；不选就用服务器默认模型」), unset = the server's default chat model. One call per run, ledger purpose `memory` (add to `model_usage.PURPOSES`, backstage label 「记忆整理」).
- **What the model gets:** the owner's own messages since the last review (newest last, each with its id and date; cut to the newest 300 or 60,000 chars), his current profile items and views (so it does not re-propose them), and a fixed instruction: find habits (how he asks, what he looks at first, when he asks) and current interests he did not state as a rule; for each, a one-line Chinese description (≤ 80 chars) and 2–5 examples, each an exact quote from one of his messages with its id; propose at most 8; nothing about his finances' merits, no advice, no guesses about his identity beyond what the messages show.
- **Code checks every proposal before storing:** each example's quote must be found in the message with that id (`profile.quote_in_message`), the message must be the owner's and inside the window, at least 2 distinct messages per item, text ≤ 80 chars; failing items are dropped and counted (`dropped` in the run record). Duplicates of an active item (same text after folding) are dropped.
- **Storage:** profile items get origin `pattern` and status `proposed` (both new values; the per-turn extractor's `inferred` items and everything else are unchanged), `examples` JSON column (list of `{message_id, quote, date}`), `review_run` id. Proposed items count against no cap of explicit items; at most 20 proposed at once (oldest proposed dropped first).
- **Light use:** proposed items go into the profile block in their own short section 「我的推测（未经你确认）：只影响回答的详略和先后，不影响结论和数字」, at most 8 lines, after his own items; the kernel system text gets no new rule beyond that heading.
- **Asking him:** after a run with at least one new proposal, one assistant message in the default bot's conversation, marked system-posted like the 3b job messages (web shows 「任务」, the next turn does not read it as his words): 「这个月我对你的了解多了这几条，对吗？」 + numbered items with one example each + 「在记忆页确认或删掉；也可以直接告诉我哪条不对。」 plus the change note line (新记 N 条推测、确认了 M 条、删掉 K 条 since the last review — counts from code). One channel notice through `app/channels.py` (source `memory`, its own daily cap 1). A run with nothing new posts nothing.
- **His answers:** confirming = existing `POST /agent-chat/profile/{id}/confirm` (proposed → active, origin stays `pattern`, label 你确认的推测); rejecting = delete on the page, or `act(forget)` in chat (works on proposed items; tier 1 as today). Proposed items older than 60 days without an answer are archived by the next run (counted in the change note).
- **Visibility:** `work.list_for` shows the memory job (next due, last outcome) so 「你手上有什么事」 knows; backstage usage groups show 「记忆整理」.
- Old engine and guests: unchanged (guests have no profile). Tests: files you touch, never the whole suite; WIP-commit before RED; check the branch before writing.

## Review Focus

1. Two workers tick at the same second with the job due: exactly one run, one message.
2. The model returns an example quote that is not in the cited message, or cites another owner's / an out-of-window message: that item is dropped, the rest stored.
3. The box was down for 40 days: one run at the next tick, not two; next due 30 days after that run.
4. A proposed item is confirmed on the page: it leaves the 推测 section and appears with his items; the next run does not propose it again.
5. Fewer than 10 owner messages: `skipped` with the reason, no model call, no message.

---

### Task 1: the memory calendar (backend)

Files: `app/memory_schedule.py` (table `memory_jobs` in `app/agent_chat_models.py`; `register(job, owner)`, `due(now)`, `claim(job, now) -> bool`, `finish(job, outcome, reason, now)`), `app/background.py` (loop `memory-jobs`, 600 s, running the jobs a registry maps by name), `app/work.py` (`list_for` item), tests `tests/test_memory_schedule.py` (Review Focus 1, 3; claim expiry; restart).

### Task 2: the monthly review (backend)

Files: `app/memory_review.py` (`run(owner, now) -> dict`: collect, call, check, store, post, notice), `app/agent_profile.py` (origin `pattern`, status `proposed`, `examples` column via the same additive-column pattern as `ensure_bot_column`, the block section, confirm keeps origin), `app/agent_model_roles.py` + `set_model_role` enum and description (role `memory`), `app/model_usage.py` (purpose `memory`), `app/channels.py` source `memory`, tests `tests/test_memory_review.py` (Review Focus 2, 4, 5; light-use block; the message and the change-note counts; 60-day archive).

### Task 3: the web

Files: memory page (`frontend/src/app/assistant/memory/`): a 「我的推测」 group above archived items, each with its examples (quote + date, linking to the conversation), 「对」 (confirm) and 「不对」 (delete) buttons; settings role row 「记忆整理」; backstage purpose label; i18n; tests; screenshots at 1440 and 390.

### Task 4 (controller)

Full suite on the final commit; report; box checks: register the job on the shadow with a back-dated last run, tick once, read the proposals and the message; then ship with the user's go-ahead under the standing rule.
