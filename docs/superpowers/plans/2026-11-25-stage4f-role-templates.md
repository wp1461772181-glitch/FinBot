# 4f Role Templates Implementation Plan — 「短线」「定投」「基金经理」 as starting memory and settings, nothing more

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new owner (or one who wants a fresh start) picks one of three starting setups — 短线, 定投, 基金经理 — sees exactly what it will write (memory items that say what to watch for and how to answer, routine briefs with their schedule and format, and recipes as skills set as the bot's usual skills), unticks what he does not want, and applies it. Everything it writes is ordinary memory and ordinary settings he can change or delete on the pages he already uses; he can also take a whole template back in one step. The kernel never learns what a "短线用户" is: no code path branches on the template.

**Architecture:** A data module `app/role_templates.py` holds the three templates (text only) and three service functions: `preview(owner, template, bot_id, leave_out)` (what would be created / reused / skipped and why — writes nothing), `apply(...)` (writes through the existing service functions `agent_profile.add_item`, `agent_skills.create_skill`, `agent_tasks.create_task`, `agent_bots.update_bot(skills=…)`) and `undo(owner, application_id, leave_out)`. A small table `role_template_applications` records what one application created so it can be shown and taken back. Profile items get one nullable column `template` (label only). Routes for the memory page, and two tier-2 `act` operations (`apply_role_template`, `undo_role_template`) on the existing card path so the model can do it when he asks in chat.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy (Postgres), pytest; React + TypeScript.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §6.3 (角色模板：「短线」「定投」「基金经理」各一套起步设置：盯防条件、简报格式、常用技能。只是初始的记忆和配置，不是代码分支，内核仍然不认识任何一种用户), §一 (不为每类人各做一套功能；内核对所有人相同，差别只来自它对每个人的了解), §7.3 第 5 条 and 「角色模板（6.3）就是预置的一组规则」 (the structured rule set is stage 5 — see the honesty constraint below), §十三 (第一次见面：角色模板能解决起步设置，但持仓和看法仍要靠在对话里一点点说), §15 第 10 条 (写操作分三级：改你数据的和花钱的必须你点确认). Handoff 第二部分第 3 条.

## 现状（规划时核过代码）— what a template can land on today

| 模板里要的 | 现有机制（落点） | 说明 |
|---|---|---|
| 盯防条件 | 画像条目 `agent_profile_items`（kind `instruction`/`about_me`/`preference`，全局层或某个 bot 的层） | 每轮对话（`agent_chat_stream._profile_block`）**和值班叫醒的那一轮**（`app/kernel/wake.py` 用同一个 `_profile_block`）都读它。自然语言的盯防说明今天就能影响值班判断（值班现在 `FINBOT_DUTY_MODE=shadow`：只记录不发）。 |
| 盯防条件（硬规则） | 哨兵 `sentinel/signals.py` 的价格异动规则 | 全站一套写死在代码里，不分人、没有开关；5 分钟急涨急跌对持仓**现在就是开着的**。可调的分级规则、三档灵敏度、5 分钟规则开关都是第五阶段（§7.3）。**这一片不碰哨兵。** |
| 盯防条件（价位、公告、新闻） | `portfolio_plans`（按股票的补仓/止损/目标价）、例行任务 `agent_tasks` kind `alerts`（申报/新闻/价位线） | 价位都按具体股票和价格，模板无法预设；哨兵已经盯官方公告，模板不再另建重复的盯盘任务。 |
| 简报格式 | 例行任务 `agent_tasks` kind `brief`（`instruction` ≤ 2000 字、`schedule_kind` daily/weekdays/hourly/every、`schedule_time`、`timezone`、`skill_id`、`bot_id`）+ 一条画像 `instruction` 说回答的格式 | 简报每次运行调一次模型（用 bot 的模型，`agent_task_runner.task_model`），记进用量。 |
| 常用技能 | 技能 `agent_skills`（owner 的 `mine` 技能：名字、用途、步骤、输出格式、允许的工具）+ bot 的「常用技能」`agent_bots.skills`（`clean_usual`，≤ 20） | 内置三条（财报速读、同行对比、新闻摘要）对所有人可见，不改。 |
| 已有的「模板」 | `agent_bots.TEMPLATES`（新建 bot 时填表单的捷径：公司研究员、新闻监控、财报解读） | 那是 bot 的模板，不是用户的；两者分开，不合并。 |

## Core-principle check (CLAUDE.md) — decisions made here

- **No code branch (spec, and 准则 3).** The three templates are data: text items, schedules and recipes in one module. Nothing outside `app/role_templates.py` mentions a template id; the kernel, the prompt and the duty wake read the resulting memory exactly as if the owner had typed it. A test pins this (grep the `app/` tree for the ids). The model is made more capable only by knowing more about the owner, which is the design's own rule.
- **准则 2 给足提示，用户自判 — the preview tells the truth about reach.** The card and the page say, in fixed sentences, what each part will and will not do today: the watch items are read by every answer and by the duty judgement, **and duty currently only records, it does not message** (read live from `wake.mode()`); the sentinel's own price rules do not change with a template in this version; each brief costs one model call per run. Nothing is hidden to make the template look more powerful than it is.
- **准则 1 默认相信模型 — templates add no checks.** The watch items are instructions for the model's judgement (the design's 「代码量不了的条件交给它判断」), not new code gates. No template adds a guard, a filter or a required format to answers.
- **The owner decides; everything is reversible.** Applying writes his data and creates paid briefs, so it is tier 2 (a card in chat; the page's own 「应用」 press is his click). Each part can be unticked before; each written thing is an ordinary row on its usual page afterwards; 「撤掉」 removes what is still there. Applying never archives, overwrites or evicts anything he already has: a duplicate is reused and reported, a full memory layer refuses the memory part with a reason.
- **No new obligation on the model.** The two operations are optional tools; the model is told nothing new except their one-line summaries.

## Global Constraints

- **Templates (code, `app/role_templates.py`, `TEMPLATES` dict, ids `short_term`, `dca`, `fund_manager`).** Each: `label` (短线/定投/基金经理), `blurb` (one sentence for the page), `memory` (list of `{key, kind, text}`; text ≤ 200 chars), `briefs` (list of `{key, name, schedule_kind, schedule_time, timezone, every_value?, every_unit?, instruction, skill_key?}`), `skills` (list of `{key, name, description, body, output_template, allowed_tools}` — every tool name must exist in `agent_tool_catalog.definitions()`; a test enforces it), `usual` (skill keys of this template plus built-in skill **names**). Keys are stable ASCII (`st_conclusion_first` …) so an application record survives a wording change. The exact contents are in the appendix of this plan and are implemented verbatim (wording changes later are a data edit, no code change).
- **Target layer:** body `bot_id` null = global memory layer + the default bot 「助理」 (tasks attach to it, usual skills are set on it); a bot id of his = that bot's own memory layer, tasks on that bot, usual skills on that bot. Unknown bot → 422 `unknown_bot` (the existing codes).
- **Memory items** are written with `agent_profile.add_item(owner, kind, text, quote=text, message=text, origin="manual", topic=None, bot_id=…)` and then `template=<id>` set on the row. Origin `manual` because he chose the item himself on a card/page (it ranks as his word, is never expired by the quarterly settle, never re-proposed by the monthly review). `topic` is always None so nothing of his is replaced. Additive column `agent_profile_items.template VARCHAR(32) NULL` via a new `agent_profile.ensure_template_column()` called at startup beside the other `ensure_*` calls in `app/main.py`. `serialize` gains `template` and `template_label` (the label, or ""). `_line` gains `·模板「短线」` after the kind label when `template` is set (true information for the model: the line came from a template he chose); a row without `template` renders byte-identically (pinned by the existing block tests).
  - **Capacity:** before writing, count the target layer's active items; if `active + new_items > MAX_ACTIVE_ITEMS` (30) the memory part is refused as a whole (`memory_full`, 「这一层记忆已有 N 条，再加 M 条会超过 30 条；先删几条或少勾几条」) and nothing of it is written; `_evict` must never run because of a template (it would archive his inferred items). Briefs and skills still apply when ticked.
  - **Duplicates:** an active item with the same text (folded) and kind in that layer → not written, reported as 「已有，沿用」, not recorded as created.
- **Skills** are created with `agent_skills.create_skill(owner, fields, origin="mine")`. A name already taken (`name_taken`: his own or a built-in) → not created; if the existing one is his or built-in and active, it is reused for usual skills and briefs and reported 「已有同名技能，沿用你的」. `MAX_SKILLS` reached → that skill is skipped with the reason.
- **Briefs** are created with `agent_tasks.create_task(owner, {kind: "brief", name, schedule_kind, schedule_time, timezone, every_value, every_unit, instruction, scope: "research_queue", channel: "inbox", skill_id, bot_id})`, enabled. Times are set in `America/New_York` for market-anchored briefs (DST-proof: 09:00 pre-open, 16:30 post-close) and `Asia/Shanghai` (the existing `DEFAULT_TIMEZONE`, same offset as his) for the rest. `too_many_tasks` → that brief is skipped with the reason. A brief whose name he already has (same bot, same name) → skipped 「已有同名任务」.
- **Usual skills:** the template's usual skills (resolved ids: created, reused, built-in by name) are **appended** to the target bot's `skills` (existing first, duplicates dropped, max 20 — over 20 → the extra are skipped with the reason) through `agent_bots.update_bot(owner, bot_id, {"skills": merged})`. The ids actually added are recorded.
- **Application record:** table `role_template_applications` (created by `Base.metadata.create_all`, model in `app/agent_chat_models.py`): `id` uuid pk, `owner_hash`, `template` (≤ 32), `bot_id` uuid null, `applied_at`, `undone_at` null, `created` JSON `{profile_item_ids: [], task_ids: [], skill_ids: [], usual_added: []}`, `skipped` JSON list of `{key, reason}`. Index `(owner_hash, applied_at desc)`. One owner may apply more than one template (and the same one again: duplicates are reused, so it is harmless).
- **Undo** (`undo(owner, application_id, leave_out)`): for each recorded id that still exists and is still his: profile item → `agent_profile.delete_item` (edited ones included — the undo list shows the current text so he can untick it); task → `agent_tasks.delete_task`; skill → `agent_skills.delete_skill` (only `mine`, never built-in; if a remaining task or bot still uses it, the task's `skill_id` is cleared by the existing delete behaviour — check it in the test, do not add new behaviour); usual → remove exactly the recorded ids from the bot's `skills`. Then `undone_at = now`. Anything already gone is listed as 「已经不在了」. Nothing not recorded is ever touched.
- **Routes** (owner only, `_owner_only`, beside the bots routes in `app/agent_bots_api.py`):
  - `GET /agent-chat/role-templates` → `{templates: [{id, label, blurb, memory, briefs, skills, usual, notes}], applications: [{id, template, label, bot_id, bot_name, applied_at, undone_at, still_there: {…counts}}], duty_mode}`.
  - `POST /agent-chat/role-templates/{template}/preview` body `{bot_id?: str|null, leave_out?: [keys]}` → `{will_create: […], reuse: […], skip: [{key, reason}], notes: [...]}`. Writes nothing. Registry: `_no("只预览模板会写什么，不写数据")`.
  - `POST /agent-chat/role-templates/{template}/apply` same body → `{application, created, reused, skipped}`. Registry: `_op("apply_role_template")`.
  - `POST /agent-chat/role-templates/applications/{id}/undo` body `{leave_out?: [ids]}` → `{removed, gone}`. Registry: `_op("undo_role_template")`.
  - Unknown template → 404 `unknown_template`; another owner's application → 404.
- **The `notes` (fixed sentences, shown on the page and on the card):** 「盯防类的几条会在每次回答和值班判断时读到。」 + when `wake.mode() != "on"`: 「值班现在只记录、不主动发消息（要打开请告诉我），所以这几条暂时只影响回答。」 + 「价格异动的默认提醒（哨兵）这一版不随模板改变。」 + 「每条简报每次运行会调用一次模型，记在用量里；不想要可以不勾，或之后在例行任务里暂停。」 + 「持仓、计划价位和你对公司的看法，还要在对话里慢慢告诉它。」. These are statements, not switches; nothing here reads or writes `.env`.
- **Chat:** `apply_role_template` (args `{template: "short_term"|"dca"|"fund_manager", bot: str|null (bot name or id; null = 全局+助理), leave_out: [keys]}`) and `undo_role_template` (args `{application_id: str | null}` — null means the newest not-undone application; `leave_out`), both **tier 2** (`act.TIER2`), `KERNEL_ONLY`, `OWNER_ONLY`, reversible level, executed through `agent_workflow/directory_ops.py` exactly as `set_channel_prefs` is (`NAMES`, `describe` returns the card built from `preview`, `execute` calls the service; `snapshot`/`is_stale` not needed: apply is idempotent by duplicates). Card title 「用模板起步 · 短线」 / 「撤掉模板 · 短线」; targets list every item that will be written/removed. `act.SUMMARIES`: 「按一个角色模板（短线、定投、基金经理）写入起步的记忆、简报任务和常用技能；会列出每一项，用户点确认才写」 / 「撤掉之前用过的角色模板加的东西（还在的那些）」. Old engine: not offered (kernel only).
- **Web:** memory page (the 4e 「它眼中的你」 tab), a section 「用模板起步」 after the summary head (4e's `MemorySummary`): three cards (label, blurb, counts 「N 条记忆 · M 个简报 · K 个技能」, 「看看会加什么」). The dialog: target selector (「全局 + 助理」 / each bot), three checkbox groups 记忆 / 简报 / 技能（含常用技能）, each item with its full text (briefs: name, when in plain words via the existing `schedule_text`-equivalent helper on the frontend, instruction), the notes, the preview result (reuse/skip lines), 「应用」. After applying: the section lists applications 「在用：短线 · 11月26日 · 全局」 with 「看它加了什么」 and 「撤掉」 (a dialog with checkboxes, current texts, 「撤掉选中的」). Profile items with `template` show a badge 「模板·短线」 in `ProfilePanel` and, instead of the quote block, 「你在 M月D日 选用模板「短线」时加的」. If 4e is not merged yet, put the section at the top of the 画像 tab; nothing else in the page changes.
- Old engine, guests: unchanged (guests have no profile; the routes are owner-only). No model call in apply/undo/preview. Tests: files you touch, never the whole suite during tasks; check the branch before every commit; WIP-commit before RED.

## Review Focus

1. Applying 短线 on an empty owner writes exactly the appendix items (origin `manual`, `template="short_term"`, global layer), 1 brief on 助理 with `America/New_York` 09:00 weekdays and its skill, 2 skills, and sets 助理's usual skills to those + 新闻摘要; the record lists every id.
2. Applying with 27 active global items and 5 template memory items → `memory_full`, none of the 5 written, no inferred item archived; briefs and skills still applied.
3. He already has an item with the same text, a skill named 「盘前速览」, and a task 「盘前速览」 → reused/skipped with the reasons; applying the same template twice creates nothing the second time.
4. Undo after he edited one item's text and deleted one task himself → the edited one is removed if ticked, the deleted task is listed 「已经不在了」, his own unrelated items, tasks, skills and usual skills are untouched, built-in skills are never deleted.
5. The kernel prompt, the profile block of an owner without template items, the wake prompt and the old engine are byte-identical (existing pins); `grep -rn "short_term\|fund_manager\|\"dca\"" app/` finds only `app/role_templates.py` (test).
6. In chat: 「我是做定投的，按定投帮我设一下，简报不要」 → one tier-2 card listing the items without the brief; pressing it writes them; a guest or the old engine never sees the operations; the registry test passes.
7. The card and the page say 「值班现在只记录…」 while `FINBOT_DUTY_MODE` is unset/shadow and drop that sentence when it is `on` (monkeypatch the env in the test; nothing writes the env).

---

### Task 1: the template data, column and record (backend)

**Files:** create `app/role_templates.py` (only `TEMPLATES`, `NOTES`, validators and `templates()` in this task); `app/agent_chat_models.py` (`RoleTemplateApplication`); `app/agent_profile.py` (`ensure_template_column`, `serialize` fields, `_line` tag, a `set_template(owner, item_id, template)` helper that sets the column without touching `updated_at`/`last_seen_at`); `app/main.py` (call the ensure at startup next to `ensure_profile_review_columns`); tests `tests/test_role_templates.py` (data validity: every tool in the catalog, texts ≤ 200, instructions ≤ 2000, schedule fields accepted by `agent_tasks.preview_task`, built-in names exist in `agent_skills.BUILTINS`, keys unique; Review Focus 5's grep test) and `tests/test_agent_profile.py` additions (column idempotent, block line with and without template).

- [ ] `TEMPLATES` exactly as in the appendix.
- [ ] `ensure_template_column()` (ALTER … ADD COLUMN IF NOT EXISTS; fresh DB from the model).
- [ ] `_line` tag and `serialize` fields; the existing block pin tests unchanged.

### Task 2: preview, apply, undo (backend)

**Files:** `app/role_templates.py` (`preview`, `apply`, `undo`, `list_applications`, `notes(duty_mode)`), `app/agent_bots_api.py` (four routes), `app/kernel/operation_registry.py`, tests `tests/test_role_templates.py` (Review Focus 1–4, 7; preview writes nothing — row counts before/after).

- [ ] `preview` resolves the target, computes create/reuse/skip per key with the reasons in Global Constraints, never writes.
- [ ] `apply` = `preview` then writes in this order: skills → memory (capacity check first, all-or-nothing for the memory part) → briefs (with the resolved skill ids) → usual skills; the record row last, in the same call; an exception mid-way leaves what was written recorded (write the record with what exists in a `finally`, so undo can still find it).
- [ ] `undo` as specified; `list_applications` with `still_there` counts.
- [ ] Routes and registry entries.

### Task 3: the operations (backend)

**Files:** `app/agent_tool_catalog.py` (args models `ApplyRoleTemplateArgs`, `UndoRoleTemplateArgs`; entries `reversible`; add both to `OWNER_ONLY` and `KERNEL_ONLY`), `app/kernel/act.py` (`TIER2`, `SUMMARIES`), `app/agent_workflow/directory_ops.py` (`NAMES`, `EXECUTED`, `describe`, `execute`, `lookup` lists the templates and his applications), `app/agent_workflow/tools.py` (the reversible dispatch set at line ~308 that names the directory ops), `app/agent_workflow/direct.py` `WRITE_TITLES`, the tool-label test the 3d note warns about (`tests/test_agent_tool_labels.py`) and the frontend tool label map if that test requires it; tests `tests/test_role_template_ops.py` (Review Focus 6 with a scripted model, card contents, guest refusal).

- [ ] Follow `set_channel_prefs` end to end (grep every place it appears; each needs the same line for the two new names — `KERNEL_ONLY`, `OWNER_ONLY`, `directory_ops`, `tools.py`, `act.py`, registry).
- [ ] The card's targets list every item; `alternative` carries the notes.

### Task 4: the web

**Files:** `frontend/src/api/role-templates.ts` (new), `frontend/src/role-templates.mjs` + `.d.mts` (pure helpers: group items, when-text for a brief schedule, count line, undo rows; tests in `frontend/scripts/role-templates.test.mjs`, appended to `test:i18n`), new `frontend/src/app/assistant/memory/RoleTemplatesPanel.tsx` and its dialogs, `MemoryPage.tsx` (placement), `ProfilePanel.tsx` (template badge and the 「选用模板时加的」 line instead of the quote, nothing else), `frontend/src/memory-items.mjs` (a `templateNote(item, locale)` helper + its test), `frontend/src/api/memory.ts` (`template`, `template_label` on `ProfileItem`), i18n; screenshots 1440 and 390 (fixtures for `GET /agent-chat/role-templates` and the preview), `npx tsc -b`, `npm run build`.

- [ ] Cards, preview dialog with checkboxes (default all ticked) and target select, applied list, undo dialog.
- [ ] Errors (`memory_full`, `too_many_tasks`, `unknown_bot`) shown with their Chinese reasons via `ErrorBar`.

### Task 5 (controller)

- [ ] Related tests, then the full suite on the final commit; frontend checks; report `docs/reports/2026-11-stage-4f.md`.
- [ ] Shadow (box): apply each template to a throwaway bot in the shadow DB, read the profile block and the wake prompt of one replayed alert (shadow has no bridge; the outbox only), run one brief per template by back-dating `next_run_at`, read the three outputs; undo all three and check row counts return to the start; `down`.
- [ ] PR; check CI myself; merge and ship under the standing rule (backup before the swap). **Do not apply any template to the owner's live data** — that is his choice on the page.

---

## Appendix: the three templates (implement verbatim)

Built-in skills referred to by name: 财报速读、同行对比、新闻摘要 (`agent_skills.BUILTINS`).

### 短线 `short_term`

- blurb: 「看日内和几天内的走势：回答先给结论和价位，急涨急跌也告诉你，开盘前给一份速览。」
- memory:
  - `st_about` about_me: 「我主要做短线，关注日内和几天内的走势，持有时间短。」
  - `st_conclusion_first` instruction: 「回答先给结论和关键价位，再讲原因；提到价格都写明是几点的数据。」
  - `st_fast_moves` instruction: 「我的持仓盘中出现急涨急跌（5 分钟、15 分钟这种），也算值得告诉我的事。」
  - `st_why_moving` instruction: 「说异动时先讲是它自己的事，还是大盘、板块一起动，再讲原因；查不到原因就直说没查到。」
  - `st_news_impact` preference: 「新闻和公告先说对股价的直接影响，背景放后面。」
- briefs:
  - `st_premarket` 「盘前速览」 weekdays 09:00 `America/New_York`, skill `st_skill_premarket`, instruction: 「开盘前给我一份速览：持仓和研究队列里，隔夜有公告、新闻或盘前涨跌明显的，每只一句话——发生了什么、盘前涨跌多少、离我设的补仓价/止损价/目标价还有多远。没有值得说的，就只回一句『今天盘前没有要特别注意的』。」
- skills:
  - `st_skill_premarket` 「盘前速览」 — description 「开盘前把持仓和研究队列过一遍：隔夜公告、新闻、盘前涨跌和离计划价位的距离。」; body 「1. 用 query_portfolio 读持仓和计划价位，用 query_research_queue 读研究队列。\n2. 用 query_market_quote / query_stock_prices 看每只的最新价和相对昨收的涨跌，写明数据时间。\n3. 用 query_sec_filings 和 search_configured_news 找隔夜的公告和新闻；不够再用 web_research。\n4. 离计划价位的距离用 calculate 算。\n5. 只写有事的那几只，每只一句；都没事就说没事。」; output_template 「**今天要注意的**（每只：公司 · 发生了什么 · 盘前涨跌（时间）· 离计划价位）\n**没事的**（一行列出）」; allowed_tools `query_portfolio, query_research_queue, query_market_quote, query_stock_prices, query_sec_filings, search_configured_news, web_research, calculate`.
  - `st_skill_why` 「异动归因」 — description 「一只股票为什么大涨大跌：先看公告和新闻，再看大盘和同行。」; body 「1. 用 query_market_quote / query_stock_prices 确认涨跌幅和时间。\n2. 用 query_sec_filings 看最近的官方公告，用 search_configured_news 看新闻；不够再用 web_research，必要时 search_x（标明是社交平台内容）。\n3. 用 query_stock_prices 看大盘和一两家同行同一时间的涨跌，分清是它自己的事还是一起动。\n4. 写原因时带出处；查不到就直说没查到。」; output_template 「**涨跌**（多少，几点）\n**原因**（带出处；没查到就写没查到）\n**是它自己还是一起动**」; allowed_tools `query_market_quote, query_stock_prices, query_sec_filings, search_configured_news, web_research, search_x, query_alerts`.
- usual: `st_skill_premarket`, `st_skill_why`, 新闻摘要.

### 定投 `dca`

- blurb: 「长期按节奏买入、不择时：日常涨跌不打扰你，每月复盘一次持仓和你的判断。」
- memory:
  - `dca_about` about_me: 「我做长期定投，按固定节奏买入，不做择时。」
  - `dca_quiet` instruction: 「日常涨跌不用特意告诉我；持仓公司的重要公告、财报，或明显超出平时波动的大跌，才值得说。」
  - `dca_no_timing` instruction: 「谈买卖时从长期基本面和我的定投计划出发，不给短线择时的建议。」
  - `dca_reading` preference: 「财报先看收入、利润和现金流的长期趋势，还有分红和回购；同比优先于环比。」
- briefs:
  - `dca_monthly` 「每月定投复盘」 every 30 days at 10:00 `Asia/Shanghai`, skill `dca_skill_review`, instruction: 「按『定投复盘』的步骤给我一份月度复盘：每只持仓的成本、现价、浮盈亏和占比，和上次比的变化；这段时间持仓公司有没有改变长期判断的事（财报、指引、重要公告）；我记下的看法现在还成立吗。不给择时建议。」
- skills:
  - `dca_skill_review` 「定投复盘」 — description 「定期看一遍持仓：成本、占比、长期基本面的变化和你当初的判断。」; body 「1. 用 query_portfolio / query_holdings_overview 读每只持仓的成本、现价、浮盈亏和占比。\n2. 用 query_financials 看最近一期和去年同期的收入、利润、经营现金流；需要的比率用 calculate 算。\n3. 用 query_sec_filings 看这段时间的重要公告和指引。\n4. 对照系统里记下的他的看法，说哪些依据还在、哪些变了；只讲依据，不给择时建议。」; output_template 「**持仓一览**（表格：公司 / 成本 / 现价 / 浮盈亏 / 占比）\n**基本面有没有变**\n**你的看法还成立吗**」; allowed_tools `query_portfolio, query_holdings_overview, query_financials, query_sec_filings, query_stock_prices, calculate`.
- usual: `dca_skill_review`, 财报速读.

### 基金经理 `fund_manager`

- blurb: 「按组合来管：盯集中度和回撤，收盘给一份组合日报，判断都写依据和反方。」
- memory:
  - `fm_about` about_me: 「我按组合来管理，关心整体风险、集中度和相对大盘的表现。」
  - `fm_limits` instruction: 「单只持仓占总资产超过 25%，或组合一天跌超过 3%，值得告诉我。」
  - `fm_position_context` instruction: 「谈个股时顺带说它在组合里的占比和对组合的影响。」
  - `fm_both_sides` instruction: 「每个判断写清依据，也写反方的看法。」
  - `fm_format` preference: 「数字尽量用表格，金额用美元，比例保留一位小数。」
- briefs:
  - `fm_daily` 「收盘组合日报」 weekdays 16:30 `America/New_York`, skill none, instruction: 「收盘后给我一份组合日报：总资产和当日涨跌，贡献最大和拖累最大的各三只，占比的变化，今天持仓公司的公告和重要新闻；超过我说过的集中度或回撤线的单独标出来。」
  - `fm_weekly` 「每周组合体检」 every 7 days at 10:00 `Asia/Shanghai`, skill `fm_skill_check`, instruction: 「按『组合体检』的步骤做一次周度体检，重点写这一周变了什么。」
- skills:
  - `fm_skill_check` 「组合体检」 — description 「看组合整体：集中度、各只的贡献、相对大盘的表现和主要风险。」; body 「1. 用 query_portfolio / query_holdings_overview 读持仓、占比和总资产。\n2. 用 query_stock_prices 看各只和大盘（如 SPY）同一段时间的涨跌；贡献和相对表现用 calculate 算。\n3. 标出占比最高的几只和超过他说过的上限的。\n4. 用 query_financials / query_sec_filings 看重仓公司最近有没有基本面变化。\n5. 每条判断写依据和反方看法。」; output_template 「**组合概况**（总资产、期间涨跌、相对大盘）\n**集中度**（表格：公司 / 占比 / 期间贡献）\n**要留意的风险**（每条带依据和反方）」; allowed_tools `query_portfolio, query_holdings_overview, query_stock_prices, query_market_quote, query_financials, query_sec_filings, calculate`.
- usual: `fm_skill_check`, 同行对比, 财报速读.

## 待 owner 定

1. **三套模板的具体内容**（附录里的每条记忆、简报时间和技能步骤）。推荐：先按附录上线，之后在实际用的过程中改字——都是数据，改一处文字不动代码。尤其「基金经理」里的 25% / 3% 两条线是我定的起步值，请看一眼。
2. **模板要不要现在就带「硬规则」**（例如短线打开 5 分钟急涨急跌、定投调成「安静」档）。推荐：这一片不带；哨兵的规则现在不分人、没开关，要等第五阶段把盯防规则做成每人可调后，再把预置规则加进模板（同一个模板文件加一段）。这一版页面上如实写明「价格异动的默认提醒不随模板改变」。
3. **值班开不开。** 模板里的盯防说明要在值班打开（`FINBOT_DUTY_MODE=on`）后才会变成主动提醒；现在是 shadow。这一片不碰这个开关，页面上如实提示。开不开仍由你定（交接文档第六节已有这一项）。
4. **默认要不要勾上简报。** 推荐：默认勾上（模板的意义就是起步即可用），每次运行的花费在预览里写明，可以不勾或之后暂停。
