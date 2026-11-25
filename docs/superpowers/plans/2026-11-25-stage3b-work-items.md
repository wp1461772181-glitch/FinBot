# 3b Work Items Implementation Plan — every piece of work has a status, ends with a message, and can run without the page open

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner can ask 「你手上有什么事」 and get a true answer; every chat turn and every job he started has a durable status (进行中、完成、失败、已停) that survives a restart; a turn keeps running when he closes the page and, if he was not there when it ended, he is told through his channel; a job started from a card (a forecast, an analysis, a filing fetch…) tells him when it ends, in the conversation that started it.

**Architecture:** A table `agent_work` records chat turns from start to end (the endpoint writes it; a startup sweep closes turns a restart cut off, with a message in the conversation). Background jobs keep their own tables; a read function `work.list_for(owner)` aggregates them with chat turns into one list, and the kernel gets a read tool `list_work`. Detached turns (FP13, already built, flag off) become the default. Owner-started jobs report their end through a small watcher that reads their status and posts once.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §4.8 (每件事都有一个状态：进行中、完成、失败、已停。你可以随时问「你手上有什么事」。每件事结束时一定有一条消息，失败也要说清楚失败在哪。耗时长的事自动转后台，你不用守着页面，做完它在对话里说，并按你的设置推到你的通道) and stage 3 of §十二. Interruption (§4.7) is the next slice and builds on this.

## Global Constraints

- **Statuses** are exactly `running`, `done`, `failed`, `stopped`, shown as 进行中、完成、失败、已停. A failure carries a one-sentence Chinese reason a person can read (never an error code).
- **Every item ends with a message.** A chat turn's answer is its message; a turn cut off by a restart gets a short assistant message in its conversation (「上一轮在 HH:MM 被系统重启打断了，没有答完；要我接着做吗？」); a background job's end is a message in the conversation that started it (and the channel notice below).
- **Channel notice** (through `app/channels.py`, source `work`, under the owner's preference and its own daily cap `FINBOT_WORK_DAILY_CAP`, default 10): only when nobody was reading the answer when it ended (the client had disconnected) or the work ran longer than 60 seconds and was a background job. One line: what it was, the outcome, where to read it. Never the whole answer.
- **Detached turns by default:** `FINBOT_FP13_DETACHED_TURNS` defaults to on. The bridges do not send `detach` and keep their behaviour. A detached turn still respects `MAX_TURN_SECONDS`.
- **No change to what the model is told or can do** except the new read tool `list_work` (owner only, unnumbered, progress phrase 「看手上的事」).
- Old engine: its turns are recorded in `agent_work` too (the endpoint is shared), nothing else changes for it.
- Tests: files you touch; never the whole suite. Box down: local only.

## Review Focus

1. The API restarts while a turn runs: after startup the item is `failed` with the restart sentence, the conversation has the short message, and the next turn's history treats it as unfinished exactly as today.
2. The owner closes the page mid-turn: the turn finishes, the answer is stored, one channel notice goes out; he reopens the page and sees the answer, not a duplicate.
3. A forecast started from a card fails three minutes later: one message in the conversation saying it failed and why, one channel notice; a retry of the watcher never posts twice.
4. 「你手上有什么事」 with one running turn (the one asking), one queued routine, one running analysis and yesterday's failed forecast: the answer lists them with statuses and times; nothing from another owner; a guest gets nothing.
5. Two API workers (or a restart during the watcher pass): no duplicate end messages (claim with a unique key per item).

---

### Task 1: `agent_work` for chat turns, the restart sweep

Files: `app/work.py` (table, `start_turn`, `end_turn`, `sweep_interrupted`), `app/agent_chat_stream.py` (start after the user row is written; end at each terminal path: complete, failed, cancelled, timeout; record whether a client was reading at the end), `app/main.py` (sweep at startup, before the bridges are served), tests.

### Task 2: detached by default, the background notice

Files: `app/agent_chat_stream.py` (flag default on), `app/work.py` (`notify_if_unattended`), tests including Review Focus 2.

### Task 3: owner-started jobs report their end; `list_work`

Files: `app/work.py` (`list_for(owner)` aggregating chat turns, routines, action requests started from cards with their live status, forecast/analysis/research jobs the owner started, archive builds; and a watcher pass in `app/background.py` that posts the end message and notice once per job), the kernel read tool `list_work` (catalogue, `READ_TOOLS`, unnumbered, progress phrase), tests for Review Focus 3–5. Find how a card's execution links to its job (`agent_consents` → `agent_action_requests` → `job_kind`/`job_id`) and to its conversation.

### Task 4 (controller)

Full suite once; report; box-side checks queued (close the page mid-turn on the test bot; restart the API mid-turn on the shadow).
