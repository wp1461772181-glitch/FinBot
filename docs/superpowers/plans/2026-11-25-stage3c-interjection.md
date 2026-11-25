# 3c Interjection Implementation Plan — speak while it works

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the assistant is working on an answer, anything the owner sends is acknowledged at once and handed to the running turn at the end of its current small step. The turn decides: fold it in (a supplement or correction — keep what it already found), let it run as a separate piece of work in parallel (another thing), or stop (he changed his mind). If it was writing the answer, it stops writing and decides with the half-written text in hand. Each answer carries which message(s) it answers. At most three pieces of work run at once; more wait in line, and he is told.

**Architecture:** The endpoint stops answering 409 `conversation_busy` for kernel turns. A message that arrives while a kernel turn runs in the same conversation is stored as a user row, put into the running turn's in-memory inbox, and its request streams back `received` and then the outcome (`merged`, `separate` → it becomes its own turn, `stopped`, or `queued`). The kernel checks the inbox between steps and between answer deltas; pending messages enter the conversation as the user's words, and a kernel-owned tool `handle_message` records the decision for each. Answers store `reply_to` (the user message ids they answer). Concurrency is counted per owner via `agent_work` (3b): beyond three running turns a new one waits in line.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §4.7 (插话: 立刻显示「已收到」，当前这一小步结束时交给它；补充或修正→调整、资料保留；另一件事→另起同时做；改主意→立即停下；正在写回答→停笔，带着半截内容决定；每条回答上方带一行引用；同时进行的事默认最多三件，再多就排队并告诉你).

## Global Constraints

- Kernel turns only (all six bots). Old-engine turns (guests, no bot) keep today's 409 behaviour unchanged.
- **The owner's words are the owner's words:** an interjection enters the model's messages as a user message (it is), clearly placed after the work so far, not as a system note; the system adds one short fixed note telling the model the three choices and the `handle_message` tool. Rules the model must follow are in that note and the kernel system text — no hidden ones.
- **`handle_message(message_id, decision, note?)`**, decision ∈ `merge`, `separate`, `stop`. Every pending message must get a decision before the turn's next model step that writes an answer; if the model gives none, the system treats it as `separate` (the safe default: the message still gets its own answer) and records that it defaulted.
- **Merge** keeps all tool results and citations gathered so far; the answer then covers both messages and `reply_to` lists both. **Stop** ends the running turn as `stopped` (3b status) with whatever partial answer it had and one short sentence from the model; nothing queued for that turn runs. **Separate** starts a new turn for that message, with the conversation history as of its arrival (the running turn's unfinished rows excluded).
- **Writing interrupted:** if the turn is streaming its answer when a message arrives, it stops streaming within one delta, emits `answer_paused`, and the model's next step sees its own partial text (as an assistant message) plus the new message.
- **Three at a time per owner** (`FINBOT_CONCURRENT_WORK`, default 3): the fourth waits; its stream says 「前面还有 N 件在做，排到了会开始」 and starts when a slot frees, FIFO, durable in `agent_work` (`queued` status shown as 排队中) so a restart does not lose it (the 3b sweep closes queued items cut off by a restart with the same restart message).
- **Writes stay safe:** a card proposed by a turn that is then stopped is not executed; a `merge` never lets text from the interjection execute anything (it is user text, same rules as any typed message); a tier-1 write the model makes after an interjection follows the existing read-count rule.
- Prompt caching: the history prefix of the running turn is not rewritten; the interjection is appended after the current position.
- SSE events added: `received {message_id}`, `merged {into_turn}`, `separate {turn_id}`, `stopped`, `queued {ahead}`, `answer_paused`. Existing clients that do not know them must not break (the bridges ignore unknown events — check).
- Tests: files you touch; never the whole suite. Box down: local only.

## Review Focus

1. 「顺便把 AMD 也比一下」 sent while NVDA is being fetched: merged; the answer covers both; `reply_to` has both ids; the AMD numbers are fetched in the same turn.
2. 「算了不用了」 while writing: writing stops within a delta; the turn ends `stopped` with a short acknowledgement; no card from it executes later.
3. 「另外，帮我记一下我买了 10 股 TSLA」 while answering about NVDA: separate turn starts in parallel; it proposes the trade card; the NVDA answer completes; two answers, each with its own `reply_to`.
4. A fourth piece of work while three run: queued, told how many are ahead, starts when one ends; survives an API restart as a restart-closed item, not lost silently.
5. Two interjections in quick succession before the step ends: both get a decision; order preserved.

---

### Task 1: inbox, endpoint and `handle_message` (backend)

Files: `app/agent_chat_stream.py`, `app/kernel/loop.py`, `app/kernel/toolrun.py` (the kernel-owned tool), `app/kernel/prompt.py` (the fixed note and one system-text sentence), `app/work.py` (concurrency slots and the queue), tests.

### Task 2: `reply_to` on answers

Files: the stored assistant row (`tool_calls` protocol or a column — choose and say why), the messages endpoint and history projection, backstage detail; tests.

### Task 3: the web client

Files: `frontend/src/app/chat/ChatSessionProvider.tsx`, `Composer.tsx`, `Thread.tsx` and the line store: the composer stays enabled during a kernel turn; a sent message shows 「已收到」 then 「已并入上一个回答」 / its own answer / 「已停下」 / 「排队中（前面 N 件）」; a line can show two answers in progress; each answer shows a one-line quote of what it answers when it is not directly below that message. Screenshots with sample data at 1440 and 390.

### Task 4: the bridges

Files: `scripts/run_telegram_bridge.py`, `scripts/run_wechat_bridge.py`: a second message while one is being answered goes to the API at once (no local queue for kernel bots); the bridge sends 「收到」 and later the outcome; separate answers are sent as separate messages with a short quote of the question.

### Task 5 (controller)

Full suite once; report; box-side checks queued (the five Review Focus cases on the test bot, web and Telegram).
