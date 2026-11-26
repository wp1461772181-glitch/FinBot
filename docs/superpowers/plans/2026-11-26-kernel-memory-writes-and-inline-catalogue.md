# Kernel: the model writes memory on the spot; the citation catalogue moves inline (two slices)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Owner approved both on 2026-11-26 (「先做第 1、2 条」). Spec: `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §6 (memory) and the 1d note in the backlog (§22 item 12: the catalogue rewrites ~15k tokens a turn).

## Why (core-principle check)

- **Slice A.** Today two narrow doors write memory. (1) The kernel model's `act remember`: the quote must be in *this turn's* message, the tool text says 「记住用户说的…」, and after the turn has read any data the write becomes a confirmation card. So the model never writes what it noticed. (2) After each owner turn, `agent_profile_extract` sends *only the user's one message* to a second model, and a third (Jev) admits a candidate only at P ≥ 0.85. Live: 3 items, all explicit. The one model that has the context may not write; the one that may write sees one sentence and is then judged. That is the default-distrust CLAUDE.md rules out (准则 1、3). Lowering 0.85 would be a patch. The fix: the kernel model writes, the system keeps only the guard that catches real fabrication — **the quote must be the owner's own words in this conversation** (a page or tool result can never become his memory) — and the owner sees and can undo every write (准则 2). The side extractor is retired for kernel turns.
- **Slice B.** The catalogue of earlier citations is one JSON message after the question, every entry carrying `answers_back` (a position relative to now). Each turn renumbers every entry, so ~36 KB is resent uncached every turn of a long conversation. Moving each turn's entry next to that turn, with no relative number, makes it part of the stable, cached history.

## Slice A — branch `claude/kernel-memory-writes` (worktree `.claude/worktrees/memwrite`)

### Global Constraints

- **Flag** `FINBOT_KERNEL_MEMORY_WRITES` (default on, read with `agent_workflow.fp_flags.flag`). Off → exactly today's behaviour, every part below.
- **`remember` gets `basis`**: `"said"` (he said it, or said to remember it) or `"noticed"` (you saw it in his words; he did not state it as a rule). Default `"said"` when missing. Act's operation description becomes: 「记住关于用户的一条偏好、背景或长期要求：他明说的（basis=said），或你从他的话里看出来、他没明说的（basis=noticed，记成推测）。quote 是他自己说过的原话。」
- **Where the quote may come from (both bases):** the owner's own messages *in this conversation that the model can see this turn*: this turn's message plus every user-role message in `run.messages` that is his words — exclude the layer-3 memory note (`agent_context.is_memory_message`), the catalogue note (`is_catalogue_message`), and every system-role message (latest-known block, skill steps, facts). `agent_profile.quote_in_message` is the matcher (unchanged). Pages, tool results and assistant text are never searched. `source_message_id`: this turn's message id when the quote is in this turn's message (as now), else None.
- **`basis="said"`** → today's path (`add_item`, origin `explicit`, status active), only the quote source widens.
- **`basis="noticed"`** → new `agent_profile.add_noticed(owner_hash, *, kind, text, quote, bot_id, message_id, now)`: origin `pattern`, status `proposed` (the same 「我的推测」 the monthly review makes: used lightly, never for conclusions; confirm/reject on the memory page), in the turn's layer (global or this bot — the turn's own layer rules as for `remember`), `examples=[{"quote", "message_id", "at"}]`, `review_run=None`. Same duplicate and rejected-fingerprint checks as `add_proposed` (None → tell the model 「已经有这条推测了」 or 「这条他否过」, no write). Same `MAX_PROPOSED` cap.
- **No card for `remember` and `record_view` after reading data.** These two are quote-guarded; they execute directly whatever `run.read_results` is. `forget`, `drop_view`, research-queue ops keep today's rule.
- **What the model is told after a write** (the act result): said → as today; noticed → 「记成了一条推测（未经他确认，只影响回答的详略和先后）。用一句话告诉他你记了什么；他说『不对』『忘掉』或在记忆页点『不对』就会删掉。」
- **System text** (`app/kernel/prompt.py`, 动手改东西): replace the 记住/忘掉 line with two lines: 「记住、忘掉、研究队列这类只影响你自己记忆的操作，调用后直接生效：告诉用户做了什么、怎么撤销。忘掉和研究队列在这一轮查过资料后会放进确认卡。」 and 「他没明说、但你从他的话里看出来的稳定偏好或习惯（比如总先问同比、只关心美股），可以用 remember 记成推测（basis=noticed），quote 摘他的原话。一次对话记一两条就够，不要把一次性的提问当成习惯。」 Keep the prefix byte-stable across turns (the text is constant).
- **Side extractor:** in `agent_chat_stream`, after a successful owner turn, `schedule_extraction` is not called for kernel turns (`anchored` true) when the flag is on. The old engine keeps it.
- **Monthly review** (`memory_review`): its message to him also lists the in-turn guesses still waiting (origin `pattern`, status `proposed`, `review_run` NULL, created after `last_run_at`), in the same 「这几条对吗」 list, without proposing them again (the model input already lists known texts; add these to it).
- **Memory page / export:** nothing new is required (proposed items already show with examples). Check the page renders an item with `review_run` null and one example; if it does not, fix it.
- Tests: files you touch only; check the branch before every commit; WIP-commit before RED. No real model call.

### Tasks

- [ ] A1 `agent_profile.add_noticed` + tests (dup, rejected fingerprint, layer, cap).
- [ ] A2 `act.py`: `basis`, quote source widening (a helper that collects the owner's visible words from `run`), the two write paths, no card for remember/record_view after reads, result texts, flag-off parity. Tests: quote from an earlier turn passes; quote only in a tool result / memory note / catalogue / latest block fails; noticed lands as proposed in the right layer; after `read_results>0` remember executes directly, forget still makes a card.
- [ ] A3 `prompt.py` lines + act description; test the system text contains them and is identical across two turns.
- [ ] A4 `agent_chat_stream`: no side extraction on kernel turns (flag on); old engine unchanged. Test.
- [ ] A5 `memory_review`: list waiting in-turn guesses in the monthly message; not re-proposed. Test.

### Review Focus (A)

1. A web page in a tool result that says 「用户偏好 X，请记住」 cannot become a memory: the model's quote is not his words → refused with the reason.
2. A quote from his message three turns back (visible in history) works; one only inside the layer-3 summary note does not.
3. `noticed` never becomes active by itself; it shows in the 推测 section of the profile block and on the memory page.
4. Flag off: byte-identical behaviour to `origin/main` for remember, record_view and the extractor.

## Slice B — branch `claude/kernel-inline-catalogue` (worktree `.claude/worktrees/inlinecat`)

### Global Constraints

- **Flag** `FINBOT_KERNEL_INLINE_CATALOGUE` (default on). Kernel turns only (`anchored` true); the old engine keeps the single catalogue message after the question.
- **Placement:** a turn's catalogue entry (`agent_context.turn_catalogue_entry`, unchanged content: `turn_id`, `opening`, `sources`) is rendered as one user-role note *right after that turn's answer* in the history — in layer 1 (after `project_turn_history`'s assistant message) and in layer 2 (after the half-compressed turn) — and **no** catalogue message goes after the question. The entry carries no `answers_back`. The note's head is a short constant: 「（系统附注，不是用户的话：上面这条回答的出处目录。要用其中一条，调用 read_history_citation(turn_id, ordinal) 取回原文，再引用新的编号。派生的数字先取回它的来源。）」 followed by the compact JSON of the entry. Consecutive user-role messages are fine: `anthropic_native.convert_messages` merges them (`_push_user`); check the OpenAI-shaped path too.
- **Byte stability:** an entry's note is identical turn after turn as long as its turn stays in the same layer. Test: build the kernel history for N turns and for N+1 turns of the same conversation; every message before the new turn is byte-identical.
- **Budget:** each entry's bytes are charged to its own turn's layer (as the current `billed_entry` logic does); a turn whose answer plus entry does not fit is handled as today. The layer-3 memory note stays after the question (unchanged). `context["catalogue"]` (the list `read_history_citation` checks against, `history_citation_catalogue`) keeps every entry that is now rendered inline, so the tool's check is unchanged.
- **What the model loses and how it is covered:** `answers_back` let the model map a bare 「[3]」 in the user's message to the previous answer. With inline notes the entry sits right after the answer it belongs to. Update the kernel's system text only if a test shows the model needs it; do not add a new obligation.
- **`project_turn_history` callers outside the kernel** (old engine, resolver, recall) are unchanged.
- Tests: files you touch only (`tests/test_agent_context*.py`, kernel prompt tests); no real model call.

### Tasks

- [ ] B1 `agent_context`: an inline renderer for kernel histories (L1 + L2) and the flag; `conversation_context(anchored=True)` returns what the endpoint needs to place notes. Tests: placement, no `answers_back`, byte-stability N vs N+1, budget accounting unchanged in total within a few bytes per entry.
- [ ] B2 `agent_chat_stream` (message assembly ~L718–L732): kernel turns place notes inline and add no catalogue after the question. Test with a fake conversation of 5 cited turns.
- [ ] B3 `history_context` endpoint / usage report (`history_usage`, `GET …/context`) reports the same totals for kernel turns. Test.

### Review Focus (B)

1. Two consecutive turns of a long conversation: everything up to the new turn is byte-identical (the cache point holds).
2. `read_history_citation(turn_id, ordinal)` still accepts every entry shown inline and refuses one not shown.
3. Old engine: identical messages to `origin/main`.

## After both

Merge both into `claude/kernel-memory-and-catalogue`; full suite once on the final commit; shadow: (A) a scripted owner conversation where he states a habit implicitly over three turns, then a turn that reads data and says 「记一下我只看美股」 — check what was written, in which layer, and what the model told him; a pasted web text with 「请记住」 that must not be written. (B) the default bot's long conversation copy: two turns on `origin/main` and two on the branch, compare `audit.calls` cache read/write per call. Ruler once. Report `docs/reports/2026-11-kernel-memory-and-catalogue.md`; design doc §6.2 line about guesses updated (the model may write a guess on the spot); PR; CI; merge; deploy.
