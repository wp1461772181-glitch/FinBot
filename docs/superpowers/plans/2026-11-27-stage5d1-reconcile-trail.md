# 5d-1 Number reconciliation after the answer: kept and shown in the backstage (not in the chat yet)

**Goal:** After a new-kernel answer has gone out, code checks every figure in it against everything the turn read, and keeps what it found on the answer. The backstage 「回答」 tab shows it and can filter 「数字没对上」. Nothing in the answer is blocked, cut or rewritten. Whether and how the chat shows it waits for the owner (see below).

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §9.1 (「回答先给你。发出之后，后台把回答里的数字和档案、工具结果逐个对上……不拦截、不删句、不重写」), §9.2 (the backstage 「回答」 column: 「数字对账结果」; filter 「数字没对上的」).

**The conflict to put to the owner (CLAUDE.md: name it, do not resolve it by habit):** §9.1 says the mismatch is marked next to the sentence; the owner's 11-11 decision (FP0/S0, `ROLLBACK_FORBIDDEN` on the box, shared memory) retired the old number review's user-visible marks — visible verification marks go only through the judge's single public gate. This slice therefore stores and shows the result in the backstage only; the chat display is a separate small slice once he decides between: (a) backstage only; (b) also inside the 「依据」 view a reader opens on purpose (§9.2 「对话里：每条回答可以点开『依据』，看到出处和对账标注」), nothing inline; (c) inline next to the sentence (§9.1).

**What is flagged (CLAUDE.md 准则 3: the target is fabrication; a false alarm is as bad as a miss):** a figure **no source of the turn holds at all** — not one the owner wrote himself, not one that is the sum, difference, ratio or change of the sources' figures. That is exactly what the old deterministic check already computes as `no_holder` in `app/agent_workflow/evidence.py` `answer_scope` (it uses `number_review`, which allows the user's figures and the arithmetic within its false-accept bound). No model call. A figure that is in a source other than the one its sentence cites is not flagged (a citation slip, not a fabrication); it is counted.

## Task 1 — the check (`app/kernel/reconcile.py`, new)

- `reconcile(answer: str, citations: list[dict], *, question: str, user_text: str) -> dict` →
  `{"version": 1, "figures": n, "flagged": [{"line": str (≤200), "values": [str]}], "elsewhere": n}` from `evidence.answer_scope` (read it and its helpers first; use its `no_holder` list, grouped by line; `elsewhere` = figures held by some source of the turn but not the one the sentence cites, if `answer_scope` exposes it, else omit the key). Never raises: an exception returns `{"version": 1, "error": "<ExceptionName>"}`.
- The citations are the ones the old check used: the turn's citation records **with their check text** (see how `evidence.citation_check_text` reads a citation and what `app/agent_chat_stream.py` has in hand at the `done` event — `citation_sidecar` / `_restore_citations`). Use whichever carries the source text; say in the report which.

## Task 2 — run it after the answer is stored (`app/agent_chat_stream.py`)

- For a kernel turn (`anchored`) that ended `complete`, after `append_message(...)`: schedule the check in the background (a thread via `asyncio.to_thread` inside a task that is not awaited by the response — the answer and the `done` frame never wait for it). When it finishes, write `reconciliation` into that assistant message's stored protocol (`tool_calls`), merging, not replacing. A failure is logged and leaves no key.
- Under `FINBOT_KERNEL_RECONCILE` (default on); off → nothing is scheduled.
- Nothing is added to the stream or to any channel's message.

## Task 3 — the backstage (`app/backstage_api.py`, frontend backstage 「回答」 tab)

- The answer list rows gain `reconcile`: `"flagged"` (n ≥ 1), `"clean"`, `"error"`, or null (not checked: an old turn, the switch off, a guest turn).
- The list gains a filter `reconcile=flagged` (the 「数字没对上」 filter of §9.2), next to the existing filters.
- The answer detail shows the result: how many figures were checked, each flagged line with its values, and one fixed line under them: 「这些数字在这一轮读到的资料里都找不到；不一定是错，可能是模型自己的知识或算法，请对照原文判断。」 (the owner judges; 准则 2).
- Locale entries for the new strings (zh-CN list, en-US map).

## Task 4 — measure the false alarms before it ships (`scripts/reconcile_report.py`, new)

- Shadow-only guards as `scripts/wake_replay.py` (`RULER_DATABASE_URL` == `DATABASE_URL`, database `finbot_ruler`); reads stored kernel answers (assistant messages whose protocol route is `K`, newest `--limit`, default 200), runs `reconcile` on each with the same inputs Task 2 uses, prints the flag rate and every flagged line with its answer id. Writes nothing.
- The report `docs/reports/2026-11-stage-5d1.md` lists each flagged line from the shadow run and whether it is a real mismatch; ship only if the false ones are few and understood.

## Tests

- `tests/test_kernel_reconcile.py`: a figure held by a source → clean; a figure the user wrote → clean; a sum / ratio of source figures → clean; a figure nowhere → flagged with its line; a figure in an uncited source → not flagged; an exception → `error`; a long line clipped.
- Stream: a kernel turn schedules it and the `done` frame does not wait; the result lands on the stored message; switch off → nothing; a non-kernel turn → nothing.
- Backstage API: `reconcile` on list rows, the filter, the detail; owner-only as the other routes.
- Frontend: the detail block and the filter; i18n.
- `scripts/reconcile_report.py` guards.

## Ship

Full suite on the final commit; ruler; the false-alarm measurement; report; Fable acceptance; release. The chat display is the next slice, after the owner's choice.

## Task 5 — the chat's 「依据」 (owner's choice 11-27: option (b))

The owner chose (b): the result is shown **inside the 「依据」 view only** — the chat's right panel, 「出处」 tab (`frontend/src/app/chat/SourcesTab.tsx`, opened by a citation chip or the process bar), for the round it shows. Nothing inline in the answer text; nothing on Telegram or WeChat (they have no such view).

- The chat history API that feeds a message's protocol to the web (find where the web reads a stored answer's `citations` / `audit` — `app/agent_chat_*.py` and `frontend/src/api/*`) also passes `reconciliation` for that message when present.
- At the end of the 「出处」 tab, when `reconciliation.flagged` is non-empty, a small block titled 「数字对账」: 「这一轮核对了 {n} 个数字，下面这些在这一轮读到的资料里都找不到：」, then each flagged line with its values, then the same fixed line as the backstage: 「这些数字在这一轮读到的资料里都找不到；不一定是错，可能是模型自己的知识或算法，请对照原文判断。」 When nothing is flagged: one quiet line 「数字对账：这一轮的 {n} 个数字都在资料里找得到。」 Not checked (null): nothing.
- The check lands a few seconds after the answer; the block appears when the web next reads that message (a reload, or the chat's own refresh if it re-reads settled messages — say in the report which).
- Tests: the history API passes the field; the block renders for flagged / clean / absent; i18n entries.
