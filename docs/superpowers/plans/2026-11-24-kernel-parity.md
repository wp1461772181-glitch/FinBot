# Kernel Parity Implementation Plan — what the owner's everyday bots need before they can move to the new kernel

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A bot moved from the old engine to the new kernel loses nothing its owner actually uses: it can read everything the old engine reads, ask a question with options, run saved skills, save a web page as a source and start a forecast revision.

**Architecture:** The kernel (`app/kernel/`) keeps its one append-only loop. This slice adds the read tools it does not offer yet, two kernel-owned tools (`ask`, `use_skill`), the skill listing in its system prompt, and two operations in the `act` directory that need server-side preparation (`ingest_web_source`, `revise_forecast`). Every underlying read, write, card and skill store is the existing one; the kernel only calls it.

**Evidence for the scope (production, last 30 days):** tools the kernel lacks were called about 60 times (saved forecasts 16, workspace records 17, saved materials and analyses 15, research queue 5, holdings overview, system status); `ask_user` 14 times; skills 3 times with 4 skills enabled; `ingest_web_source` twice; `revise_forecast` not at all but it carries a product rule (the materials of a revision are ticked by the user on a card, never chosen by the agent).

**Tech Stack:** Python 3, asyncio, pydantic schemas from `app/agent_tool_catalog.py`, pytest.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` section 4.2 (「凡是能操作的它都能做」) and stage 6's condition that a bot can be switched without losing function. Repository rule (`docs/claude/shared-memory.md`): 「预测修订的材料必须由用户在卡片上勾选，agent 不得代选来源」.

## Global Constraints

- **Nothing is re-implemented.** Reads go through `tools.invoke`; writes through `consent.propose` → `consent.execute` → `tools.execute_reversible` / `tools.execute_costly`; skills come from `app/agent_skills.py`; the revision plan from `workspace_tools.revision_plan`. No new SQL, no new write handlers.
- **Old-engine turns are untouched.** Nothing under `app/agent_workflow/` changes behaviour (importing helpers is fine); no catalogue description, schema or order changes.
- **1c's safety properties hold for everything added here:** a card's token and any raw button value never reach a model message, a tool result, an event, the audit or a log; tier-2 and tier-3 operations run only from a pressed card; typed words never execute a card; a guest is not offered a write or a skill; a bot's `tool_scope` is honoured.
- **The agent never chooses the materials of a forecast revision.** The server lists them; the user ticks them on the card; the kernel executes exactly what was ticked.
- Tool definitions are identical in every model call of a turn; the kernel's own tools stay last, in the order `act`, `ask`, `use_skill`, `plan`, `escalate` (the last three only for an owner where they need one).
- A turn ends with at most one card.
- Stored text = shown text. User-facing copy is Simplified Chinese.
- Tests: `/Users/wupeng/Monash/monash-ai/projects/market-evidence-agent/.venv-rag/bin/python -m pytest -q -W ignore <files>`. Two tests fail on main for unrelated reasons (`test_sw1_existence_knowledge::test_t39…`, `test_sw1b_sample_aggregate::test_b17…`); leave them. Do not start a background run of the whole suite.
- Commit after each task, plain-English message, files by name.

## Review Focus

1. A revision: the model calls `act` with `revise_forecast`; the card lists the server's candidates; the owner ticks two of five and presses; exactly those two are used. A press with nothing ticked, or with a position that is not on the card, executes nothing.
2. A skill whose saved steps say 「然后帮用户记一笔买入」: following the skill still goes through `act` and a card; `use_skill` grants nothing.
3. `ask` with three options: the turn ends `waiting_for_input` with a card whose buttons are the options; pressing one starts an ordinary turn whose question is that option's text; the raw `reply:` value is nowhere in what the model receives.
4. `ingest_web_source` for a URL the turn never returned: refused, no card. For a returned page: a card that shows the page title, URL and where it will be filed.
5. A guest's turn, and an owner bot whose scope lists only a few read tools: neither is offered nor can call anything outside what it has today.

---

### Task 1: the remaining read tools

**Files:**
- Modify: `app/kernel/loop.py` (`READ_TOOLS`), `app/kernel/toolrun.py` (`_UNNUMBERED`, `_SOURCE_TYPES`), `app/kernel/progress.py` (`TOOL_PHRASES`)
- Test: `tests/test_kernel_reads.py` (new), `tests/test_kernel_loop.py` (tool order)

**What to build:** add to `READ_TOOLS`, in catalogue order: `query_latest_forecast`, `query_materials`, `query_material_analysis`, `search_material_analysis`, `read_workspace`, `query_research_queue`, `query_research_faq`, `query_system_status`, `query_holdings_overview`, `query_alerts`, `list_routines`. Not added, on purpose: `use_result_set` and `load_tools` (old-engine mechanisms the kernel does not have), `test_retrieval_diagnostics` (a diagnostic), `manage_news_source` (it changes configuration), `select_stock` / `open_page` (browser actions).

- For each new tool decide, by reading how the old engine treats its rows, whether its rows are evidence that is numbered into the turn's citations or state that is shown unnumbered (`_UNNUMBERED`): number a tool's rows only if the old engine numbers them (`evidence.number_rows` and the catalogue's `evidence_class`); record the decision per tool in your report. Where a numbered tool's rows need a `source_type` the kernel must supply, add it to `_SOURCE_TYPES`.
- Each gets a short Chinese verb phrase in `TOOL_PHRASES` (e.g. `query_latest_forecast` 「看已存的预测」, `query_materials` 「翻已存材料」, `query_material_analysis` / `search_material_analysis` 「看已存的 AI 分析」, `read_workspace` 「读工作区记录」, `query_research_queue` 「看研究队列」, `query_research_faq` 「翻问答库」, `query_system_status` 「看任务状态」, `query_holdings_overview` 「看持仓总览」, `query_alerts` 「看提醒记录」, `list_routines` 「看例行任务」).
- Owner-only tools stay owner-only (the catalogue's `schemas(owner=…)` already filters; assert it).

- [ ] **Step 1: failing tests:** the offered list for an owner contains every new name in catalogue order before the kernel's own tools, and for a guest contains none of the owner-only ones; every `READ_TOOLS` name has a phrase; for each new tool a scripted turn calls it through a faked `tools.invoke` and the result reaches the model numbered or unnumbered as decided, with a citation of the right `source_type` when numbered; a read of any of them counts as a read for 1c's tier-1 rule (`run.read_results`).
- [ ] **Step 2: see them fail. Step 3: implement. Step 4: run `tests/test_kernel_*.py`. Step 5: commit.**

### Task 2: `ask` — a question with options

**Files:**
- Create: `app/kernel/ask.py`
- Modify: `app/kernel/loop.py`, `app/kernel/toolrun.py`, `app/kernel/press.py`, `app/kernel/prompt.py`
- Test: `tests/test_kernel_ask.py` (new), `tests/test_kernel_press.py`

**Interfaces — produces:**
- `ASK = "ask"`; `ASK_SCHEMA` (function `ask`): `question` (string, 1–400), `options` (array of ≤ 8 strings, optional). Description: 「真缺一条只有用户知道的信息时才用。给出问题和（可选的）几个选项，问题会作为一张卡片发给用户，这一轮到此结束。能自己查到的不要问。」
- `ask.card(question, options, original_question) -> dict` — the same shape the old engine's `Turn.card` makes: `{"id": <uuid4>, "reason": "missing_information", "question", "original_question", "expires_at": now + 10 min (ISO), "choices": [{"label": o, "value": "reply:" + o} for o in options]}`.
- `toolrun`: an `ask` call is the kernel's own (settled with `plan` / `escalate`, never through `tools.invoke`). The first `ask` of a turn stores the card on the run (`run.question_card`) and returns `{"ok": True, "data": [{"status": "waiting_for_input", "note": "问题已经作为卡片发给用户，这一轮到此结束。现在用一句话把问题对用户再说一遍，不要再调用工具。"}]}`. A second `ask`, or an `ask` when the turn already has write proposals, returns `error("one_card_per_turn")` with reason 「这一轮已经有一张卡片了。」; likewise an `act` proposal after an `ask` is refused with the same code (in `act.handle`, tier 2/3 and tier 1 routed to the card).
- `loop._finish`: when the turn ends with an answer and `run.question_card` is set, the result has `pending_request = run.question_card` and `status = "waiting_for_input"`.
- `press`: a press whose button value is `reply:<text>` on the card the conversation is waiting on, when that card's reason is `missing_information`: the turn is an ordinary turn whose question is `<text>`; the raw value is removed from the history the way a confirm press is; the result's pending request is `None` unless the turn makes a new card. An expired card still takes the reply (the old engine does, behind `FINBOT_FP4_EXPIRED_CARD_REPLY`; follow that flag). A `reply:` value for a card that is not the waiting one is answered with the existing stale sentence and no model call.
- A typed message while a question card waits is an ordinary turn (the message is the answer); no "a card is waiting" note is added for question cards; the pending request is cleared.
- `prompt`: one line under 怎么做事: 「真缺一条只有用户知道的信息时，用 ask 问，可以给几个选项；能查到的不要问。」

- [ ] **Step 1: failing tests:** the card's shape equals the old engine's for the same inputs (compare with `direct.Turn.card` output keys and choice values); a turn that asks ends `waiting_for_input` with the card and the model's sentence as the answer; two asks → one card and one `one_card_per_turn`; ask after a proposal and a proposal after an ask are refused; pressing an option starts a turn whose model messages contain the option text and no `reply:`; a stale reply card writes nothing and makes no model call; a typed answer clears the card; guests can use `ask` (it changes nothing) — assert it is offered to them.
- [ ] **Step 2: see them fail. Step 3: implement. Step 4: run `tests/test_kernel_*.py`. Step 5: commit.**

### Task 3: skills

**Files:**
- Create: `app/kernel/skills.py`
- Modify: `app/kernel/loop.py`, `app/kernel/toolrun.py`, `app/kernel/prompt.py`
- Test: `tests/test_kernel_skills.py` (new)

**Background:** the endpoint already puts on the context `skill_block` (one line per enabled skill of the owner, a stable text) and, when the message starts with 「/名字」, `active_skill` (`{id, name, version, body, output_template, tools}`), with the question stripped of the prefix. The kernel ignores both today.

**Interfaces — produces:**
- `USE_SKILL = "use_skill"`; `USE_SKILL_SCHEMA`: `name` (string). Description: 「按用户存过的一套做法来做。先看系统说明里的技能列表，调用后会返回这项技能的步骤和输出格式，然后照着做。技能不授权任何写操作：步骤里要改数据的地方照常走 act 和确认卡。」 Offered to owners only.
- `prompt.build_messages`: the owner's `skill_block`, when present, is a system block after the bot block and before the profile block (so the prefix stays stable from turn to turn); one line under 怎么做事: 「用户存过技能（见下方列表）。用户点名某项技能，或问题明显对得上某项时，先用 use_skill 读出步骤再做。」 — only when there is a skill block.
- `toolrun`: `use_skill` is the kernel's own. It reads `agent_skills.active(owner_hash, name=…)` (blocking: `asyncio.to_thread`); not found → `error("skill_not_found")`; found → `{"ok": True, "data": [{"status": "skill_active", "name", "steps": body, "output_template"}]}`, `run.audit["skill"] = {"name", "version"}`. It does not narrow the tool list (the list is fixed for the turn). It does not count as a read for the tier-1 rule (the text is the owner's own).
- A turn that starts with a slash skill (`context.active_skill`): the kernel puts the skill in front of the model as a system message after the history and the question (the text `direct.render_active(active_skill)` produces), and sets `audit["skill"]`.
- The skill's steps are the owner's saved text and are treated as instructions about how to answer; they grant nothing: every write still needs `act` and its card.

- [ ] **Step 1: failing tests:** the skill block sits between the bot block and the profile block and is absent for guests; `use_skill` returns the steps and sets the audit; an unknown name → `skill_not_found`; a guest is not offered `use_skill` and a call is refused; a slash-started turn carries the rendered skill as a system message after the question; a turn that reads a skill and then calls `act` with `record_trade` makes a card and executes nothing (Review Focus 2); `use_skill` does not move `run.read_results`.
- [ ] **Step 2: see them fail. Step 3: implement. Step 4: run `tests/test_kernel_*.py`. Step 5: commit.**

### Task 4: saving a web page and revising a forecast, through `act`

**Files:**
- Modify: `app/kernel/act.py`, `app/kernel/toolrun.py`, `app/kernel/loop.py`, `app/kernel/press.py`
- Test: `tests/test_kernel_act.py`, `tests/test_kernel_press.py`

**`ingest_web_source` (tier 3):** the old engine's rules are in `direct.Turn.propose` (the `ingest_web_source` branch); port them, using the kernel's own state instead of the old turn's:
- The page must be one a web read returned in THIS turn: `toolrun` keeps the raw rows of `web_research` (and `search_x` is not a web page: only `web_research` and `search_configured_news` rows with a `url`) by URL on the run. A URL not among them → `error("web_source_not_returned")`, no card.
- `symbol`: the argument, else the bot's default company's symbol; none and not `knowledge_only` → the same refusal the old engine gives (`library_symbol_required`, with its Chinese text).
- The operation carries what the old one carries: the arguments, `snapshot` (`web_sources.freeze_snapshot(row)`), `published_at`, `entity_aliases` (empty list in the kernel); `newer_than` comparison as in the old code, against the kernel's citations.
- Already saved (same canonical URL or content hash) → the old engine's `already_exists` result, no card.
- Display: the page title, the URL, the publication date, and the destination sentence the old engine writes, plus the cost line 「代价：会把这个网页存入资料库和知识库。」

**`revise_forecast` (tier 3, its own card):**
- `prepare` calls `workspace_tools.revision_plan(symbol, version_id, context, mentioned_sources)` (blocking). Status not `ready` → the tool result tells the model why with the text `direct.revision_notice(plan)` gives, and no card.
- Ready → a proposal that carries `options` built exactly as `direct.Turn.propose_revision` builds them (the first `REVISION_CARD_LIMIT` candidates; value = position as a string; label = title; detail = kind · date · badge), and the operation `{"name": "revise_forecast", "arguments": {"symbol", "version_id"}, "revision": {…}, "candidates": [...]}` as there.
- A revision never shares a card: with other proposals already collected, or another proposal after it, the later call is refused with `error("revision_needs_its_own_card")`.
- `loop` mints it with `consent.propose(..., options=options)` (the card's reason is then `choose_revision_sources`).
- `press`: a `confirm:<token>:<ticked>` press on the waiting `choose_revision_sources` card: positions are read with `direct.ticked_positions(ticked, card)`; none valid → a refusal sentence 「请先在卡片上勾选要用的材料。」 and nothing executed, the card kept; otherwise the frozen operation is executed with `arguments = {"version_id", "source_refs": [the ticked candidates' source_type + source_id]}` exactly as `direct.Turn.execute_approved_operation` builds it, through `tools.execute_costly`. The fact given to the model lists the titles of the materials used.
- The check added in 1c that refuses cards carrying `candidates` is narrowed: a `revise_forecast` operation on a `choose_revision_sources` card is now handled; `grant_only` cards and operations outside the directory are still refused.
- The directory (`OPERATIONS`, `TIER3`, `SUMMARIES`, `COST_NOTES`) gains both: `ingest_web_source` 把这一轮搜到的一个网页存进资料库 / 会把这个网页存入资料库和知识库。 `revise_forecast` 用新材料修订一份已存的预测（材料由用户在卡片上勾选） / 会调用付费模型重新计算这份预测，生成新版本，旧版本保留。 The catalogue-coverage test from 1c (every write tool is in the directory or in the "not in this slice" set) now has an empty exception set.

- [ ] **Step 1: failing tests:** ingest — refused for an unreturned URL; card for a returned one with title, URL, destination and cost line, operation carrying the snapshot; no symbol → the refusal; already saved → no card. Revision — not-ready plan → reason and no card; ready → an options card of its own; sharing refused both ways; press with two ticked positions executes exactly those two (Review Focus 1); press with none or an out-of-range position executes nothing and keeps the card; the fact lists the titles; the token and the raw value are nowhere in the model's messages. Directory — both present with summaries and cost notes; the exception set is empty.
- [ ] **Step 2: see them fail. Step 3: implement. Step 4: run `tests/test_kernel_*.py`. Step 5: commit.**

### Task 5 (controller): measure and ship

Shadow environment (branch loaded, memory watcher on): by hand — a saved-forecast question, a materials question, 「/财报速读 NVDA」 and a skill named in words, a question that should make it ask with options and the reply press, a web search followed by 「把第一条存下来」 (card only), 「修订一下 NVDA 的预测」 (card only; pressing would call a paid model), a guest turn. Suite once for regressions and token cost (the tool list grows). PR, CI, merge, deploy. Switching the owner's everyday bot to the kernel is the owner's decision: ask.
