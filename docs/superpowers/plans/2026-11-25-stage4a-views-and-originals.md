# 4a Your Views and Reading Back Originals Implementation Plan — the first slice of memory

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two things stage 4 needs before anything monthly or quarterly can be built: (1) the owner's view of each company he follows, said in his own words, recorded on the spot, shown whenever that company comes up, with every earlier version kept and dated so he can see when he changed his mind; (2) a way for the model to read back the original text of an earlier turn, so a summary only points at the turn and details come from what was actually said.

**Architecture:** A new table `owner_views` (owner, symbol, text, the owner's quote, the message it came from, status, dates) in a new module `app/owner_views.py`, written by a new tier-1 `act` operation `record_view` and withdrawn by `drop_view` (same safety as `remember`: runs at once unless this turn has seen a read result, then a card). The current view of each mentioned company is one line in the 「系统最新掌握」 block (`app/latest_known.py`). A new kernel read tool `read_turn` returns one earlier turn's user message(s) and final answer, by turn id. The web shows views on the company page (current + history) and the memory page.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy (Postgres), pytest; React + TypeScript.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §6.1 (你对每个关注对象的看法 → 档案的「你的看法」；细节只从原文来：摘要只是目录，回答细节时必须读回那一轮的原文；你明说的记忆必须有你的原话作依据), §6.2 (当场：你明说的…看法，这件事做完就记，在对话里说一声「我记下了：……」，一句话可撤销；新的盖旧的，旧的不删，能查到你什么时候改的主意), §6.3 (复盘 depends on views having a history — this slice only keeps the history).

## Global Constraints

- **The owner's words are the authority.** A view is stored only with a quote found in one of the owner's own messages of this turn (the same `profile.quote_in_message` rule `remember` uses; reuse it, do not copy it). `text` is the model's one-line rendering (≤ 200 chars), `quote` his words (≤ 400 chars). No view is ever written from a web page, a filing or a tool result.
- **New covers old, old is kept.** One active view per (owner, symbol). Recording a new one marks the previous `superseded` with `ended_at`; `drop_view` marks the active one `dropped` with `ended_at`. Nothing is deleted by the model. The web page may hard-delete one version (the owner's own click), like the memory page.
- **Symbol:** resolved through `app/company_directory.py` (the 2a name/ticker resolver); an unresolvable company is refused before anything runs, with the hint 「没认出是哪家公司；用代码再说一次」.
- **`record_view(symbol, text, quote)` and `drop_view(symbol)` are tier 1** (`act.TIER1`), exactly like `remember`/`forget`: they run at once only when this turn has not seen a read result; otherwise they go on a card. The result the model sees says what was recorded and the one sentence that undoes it (「要撤回，说『撤回我对 X 的看法』」); the model tells the owner 「我记下了：……」 in its answer — say this in the operation's description, no other rule.
- **Not a write path for anything else:** a view is not evidence and authorizes nothing; the block line says so in its fixed wording (「你的看法，不是证据」).
- **In the 「系统最新掌握」 block:** for each mentioned company with an active view, one line `你的看法（M-D 说的）：<text>` placed first in that company's section; it is the last line dropped when space is short (the owner's own words matter more than one more figure). Guests never see views.
- **`read_turn(turn_id)`** (owner and guest kernel turns; own conversation only; read tool, unnumbered like `read_past_conversation`): returns the turn's user message(s) in order and its final answer text (each ≤ 12,000 chars, marked when cut), its time, and the turn ids just before and after it. Unknown or other-conversation turn → `turn_not_found`. The memory note's fixed text (`MEMORY_NOTE` in `app/agent_context.py`) gets one true sentence: the summary is an index; for details, read the turn with `read_turn`. Old engine: the tool is not offered there and its note is unchanged (old engine byte-identical).
- **Registry:** every new mutating route maps to `record_view`/`drop_view` or is exempt with a Chinese reason (`app/kernel/operation_registry.py`; the registry test must pass). Operation directory summary lines for both.
- **Web copy** Simplified Chinese. Company page: a 「你的看法」 card (current text, his quote, date, 「历史」 expanding every earlier version with its dates and status 已更新/已撤回). Memory page: a 「你的看法」 section listing the active view per company with a link to the company page.
- Tests: files you touch, never the whole suite. Commit plainly, files by name; WIP-commit before any RED run. The box is reachable only when the owner is home: local only.

## Review Focus

1. 「我觉得英伟达今年数据中心还会翻倍」 → a view for NVDA with that quote; a week later 「我改主意了，英伟达估值太高」 → the first is `superseded` with its end date, the second active; the company page shows both in order.
2. The model calls `record_view` after a `web_research` in the same turn: a card, not a direct write; a quote not in the owner's message is refused.
3. Asking about NVDA after a view exists: the 「系统最新掌握」 block's NVDA section starts with the view line; with a tight block the facts go before the view does.
4. `read_turn` on a turn from another conversation, another owner, or a made-up id: `turn_not_found`; on a turn of this conversation: the original user text and answer, not the summary.
5. Old engine and guests: no `read_turn`, no views, no change in their prompts (pinned).

---

### Task 1: views — table, module, operations, block line (backend)

Files: create `app/owner_views.py` (table model in `app/agent_chat_models.py` beside `portfolio_plans`; `record(owner, symbol, text, quote, source_message_id, conversation_id, turn_id) -> dict`, `drop(owner, symbol) -> dict | None`, `current(owner, symbols) -> dict[symbol, view]`, `history(owner, symbol) -> list`, `delete_version(owner, id)`); modify `app/kernel/act.py` (two tier-1 operations reusing `_quote` and `profile.user_message_id`), `app/agent_tool_catalog.py` (operation descriptions), `app/latest_known.py` (the view line, owner only), routes `GET /agent-chat/views?symbol=`, `GET /agent-chat/views/{symbol}/history`, `DELETE /agent-chat/views/{id}` (owner only) in the module that holds the profile routes, `app/kernel/operation_registry.py`; tests `tests/test_owner_views.py` (Review Focus 1–3, guest refusal, registry).

### Task 2: `read_turn` (backend)

Files: `app/agent_chat_store.py` (a reader by conversation + turn id, owner-checked), the kernel read tool (catalogue entry, `READ_TOOLS`, `_UNNUMBERED`, progress phrase 「翻看之前那一轮」), `app/agent_context.py` (`MEMORY_NOTE` sentence, kernel only), tests `tests/test_read_turn.py` (Review Focus 4–5, cut marking, neighbours).

### Task 3: the web

Files: the company page card and history (`frontend/src/app/research/CompanyOverview.tsx` or a new component beside it), the memory page section (`frontend/src/app/assistant/memory/`), API helpers, i18n, tests; screenshots at 1440 and 390 with sample data (a company with three versions: active, superseded, dropped).

### Task 4 (controller)

Related tests, full suite once, report; box checks queued (record a view on the test bot, change it, see the block line and the company page).
