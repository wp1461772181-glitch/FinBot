# 3d Helper Implementation Plan — send the legwork out, keep the judgment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When one piece of legwork itself takes several steps (read three earnings calls and pull out what each says about capex), the turn can hand it to a helper: a short-lived low-tier run with a short brief and the read tools it needs, which comes back with its findings and their sources. Comparing, judging and writing the conclusion stay with the turn. Behind a switch, off by default, until the ruler has measured it.

**Architecture:** A kernel-owned tool `delegate(brief, tools?)` in a new module `app/kernel/helper.py`. It runs a child run with the existing model-call and tool-step code: its own messages (a fixed helper system text + the brief), read tools only, tier `low`, its own step and time caps. The child shares the parent's citation list, web rows and result sets, so every `[n]` it writes is a valid number in the parent turn and `act` can save a page it read. Several `delegate` calls in one step run at the same time, like reads. The child stops early when the owner sends a message to the running turn (its steps are the turn's small steps).

**Tech Stack:** Python 3, asyncio, pytest.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §4.6 (互不依赖的跑腿活同时进行；一项跑腿活本身要好几步时，派给一个低档的小助手去做。它只拿到一段简短的交代和用得上的工具，做完交回结果和出处。对比、判断、写结论不派出去…；小助手…放到第三阶段，用尺子量过质量再默认打开), §十四 point 8 (小助手开关 is configurable) and decision 5 in §十五 (判断和写结论不派出去).

## Global Constraints

- **Switch:** `FINBOT_HELPER` (`on`/`off`, default `off`). Off: nothing about any turn changes (schemas, prompt text, results byte-identical to today). On: `delegate` is offered to owner and guest kernel turns that have at least one read tool; never to wake turns, never to old-engine turns, never inside a helper (no recursion).
- **What the helper gets:** a fixed system text (Chinese, short: it is a helper doing one piece of legwork for the assistant; read what the brief needs; report what it found with the `[n]` numbers of the results; say plainly what it could not find; no judgment or advice; today's date), the brief as the user message, and the read tools the parent turn has (`tools` narrows them; a name not offered to the parent is refused before anything runs). No `act`, `ask`, `use_skill`, `plan`, `escalate`, `handle_message`, `delegate`, `decide`. Calculations are allowed (they are offered to the parent as tools).
- **Model:** the model role `helper` when the owner has set one (add `helper` to `agent_model_roles.ROLES` and the `set_model_role` enum; the settings role table gets a row 「小助手」 with the same control as the others); otherwise the parent turn's current model (its backup once the turn switched). Always tier `low`. No backup switch inside the helper: a failed helper returns a failure and the turn carries on.
- **Caps (module constants):** `HELPER_MAX_STEPS = 6` model steps, `HELPER_SECONDS = 120`; when a cap is hit the helper makes one closing step that must answer from what it has (the parent's `CAP_NOTE` pattern). At most `MAX_HELPERS = 3` `delegate` calls run per step; extra ones get `{"ok": False, "error_code": "too_many_helpers", "hint": …}` without running. A helper does not hold a slot of the parent's read gate.
- **What comes back** (the tool result the turn sees, unnumbered — its rows were numbered as the helper read them): `{"ok": True, "data": {"report": <the helper's final text>, "sources": [the [n] numbers it read, in order], "steps": k, "complete": bool}}`. `complete` is False when it stopped early (owner's message, time or step cap); then `report` is whatever it wrote last or 「还没写总结，已拿到的资料见 [n]…」 built by code from `sources`. A failure: `{"ok": False, "error_code": "helper_failed", "hint": "小助手没有做成，可以自己查。", "data": {"sources": […]}}` — sources it already read stay usable.
- **Counts as one read result** for the tier-1 rule (`run.read_results += 1` when it returns ok with at least one source).
- **What the owner sees:** the helper's own text never streams to the page. Its tool calls show as narration lines prefixed 「小助手：」 (the existing progress phrases), nothing else (no `tool_start`, `delta`, `answer_reset` from the child reach the client). The `delegate` call's own `say` works like any tool's.
- **Owner speaks while it works:** before each helper step, if the parent's inbox has a fresh message, the helper stops (`complete: False`) and the step ends normally, so the turn takes the message at once. A stop decision discards nothing the helper read.
- **Records:** model calls under `model_usage.purpose("helper", …)` with the parent's owner, conversation, turn and bot; the parent's audit gets `helpers: [{call_id, model, steps, model_calls, token_usage, complete, seconds, tools: [names]}]` and its token/model-call totals include the helper's; timeline entries `helper_start` / `helper_done` with the call id. The backstage turn detail lists each helper (one line: model, steps, tools, complete, seconds).
- **The model is told:** the `delegate` tool description (English like the catalogue, says: for several-step legwork that does not need the conversation, e.g. reading several filings or calls for one kind of fact; write a self-contained brief; do not delegate comparison, judgment or the answer; it comes back with `[n]` sources usable in the answer), and one true sentence in the kernel system text when the tool is offered. No other rule.
- Tests: files you touch; never the whole suite. Box down: local only. Commit plainly, files by name; WIP-commit before any RED run.

## Review Focus

1. Two `delegate` calls in one step (NVDA and AMD capex from their last calls) run at the same time; both reports' `[n]` are distinct, valid citations of the parent turn; the answer can cite them.
2. A helper asking for `act`, `ask` or `delegate` (in `tools` or by calling it) is refused; nothing is written; a guest's helper gets only the guest's reads.
3. The owner sends 「算了」 while a helper is on its third step: the helper stops before its next step, the turn handles the message, the turn ends stopped; the helper's model calls are in the ledger.
4. The helper's model fails (provider error): the turn gets `helper_failed`, carries on and answers on its own; no backup switch happened inside the helper.
5. `FINBOT_HELPER=off`: the kernel's tool schemas and system text equal today's (pinned by a test that compares them).

---

### Task 1: the helper run and the `delegate` tool (backend)

Files: create `app/kernel/helper.py` (`DELEGATE`, `DELEGATE_SCHEMA`, `enabled()`, `async def run(parent, call_id: str, args: dict) -> dict`); modify `app/kernel/loop.py` (offer the schema; one system-text sentence via `app/kernel/prompt.py`; audit merge), `app/kernel/toolrun.py` (route `delegate` as a concurrent call outside the read gate, the `MAX_HELPERS` refusal, unnumbered settle, read count), `app/agent_model_roles.py` + `app/agent_tool_catalog.py` (role `helper`), backstage detail projection; tests `tests/test_kernel_helper.py` covering Review Focus 1–5, the caps' closing step, `tools` narrowing and refusal, the event filter, the ledger purpose, and the role fallback.

Build the child from the existing `_Run` (shared `citations`, `web_rows`, `new_sets`, `context`; its own `messages`, `schemas`, `tool_names`, `audit`, `tier="low"`, `ceiling="low"`, `inbox=None`, `pausable=False`) and run its steps with the loop's own `_call_model` and `run_step_tools`, so numbering, timeouts and tool errors behave exactly as in a turn. Do not copy those functions.

### Task 2: the settings row and the backstage line (web)

Files: `frontend/src/app/settings/models/RoleTable.tsx` (row 「小助手」: 「拆出去的跑腿活用哪个模型；不设就用当时对话的模型」), the backstage turn detail component (helper lines), i18n entries, tests; screenshots at 1440 and 390 with sample data.

### Task 3 (controller)

Related tests, full suite once, report; box-side checks queued: ruler with `FINBOT_HELPER=off` vs `on` on the shadow (cases that read several documents), Review Focus 1 and 3 on the test bot; the switch stays off until the ruler shows no loss.
