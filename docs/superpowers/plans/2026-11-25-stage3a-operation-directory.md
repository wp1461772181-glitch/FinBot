# 3a Operation Directory Implementation Plan — what the owner can click, he can ask for; and nothing new slips through

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps the endpoint inventory found between what the owner can do on the page and what he can ask the assistant to do, and add an automatic check so a new state-changing endpoint cannot ship without being either reachable through `act` or deliberately exempted with a reason.

**Architecture:** Every new capability is an `act` operation in `app/kernel/act.py` (all tier 2: always a card the owner presses), executed through the same function the HTTP endpoint already calls — no second write path. One new read tool lists the model catalog. A registry file maps every `POST`/`PUT`/`PATCH`/`DELETE` route to an operation or an exemption reason; a test walks the app's routes and fails on any route missing from the registry.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §4.2 (凡是能操作的它都能做), §4.3 (谁有权让它改东西), stage 3 of §十二 (「操作目录补全并加上『不漏』的自动检查」); the inventory `docs/reports/2026-11-mutating-endpoints.md` (§二 gaps ranked by evidence, §三 recommendations, §四 surprises).

## Global Constraints

- **Every new operation is tier 2 or 3: it runs only from a pressed card.** The card says, in plain Chinese, exactly what will change, from what to what (old value → new value), and anything irreversible.
- **One write path.** An operation calls the same service function the HTTP route calls (extract a shared function where the route has its logic inline; the route then calls it too). No duplicated validation.
- **Not offered (deliberately):** deleting a bot (takes its whole conversation thread), model keys and adding catalog entries, binding Telegram/WeChat/Pushover, adding news sources (writes a URL; revisit if asked), editing memory text, renaming/archiving conversations. These go into the registry as exemptions with that reason.
- **The owner's settings are changed only by his press.** Default model, model roles and channel preference are his settings; the card is how he decides.
- **Security fix in scope:** `POST /finbot/routines/{id}/confirm` (`app/main.py` ~287) accepts a confirmation without an owner check when no `action_token` is sent. It must require a valid token (or the owner's credential); find every caller first (bridges, notification links) and keep them working.
- Copy is Simplified Chinese; tool and operation descriptions for the model are English like the rest of the catalogue. Tests: files you touch, never the whole suite. Commit plainly, files by name. The production box is down: local only.

## Review Focus

1. A card for `update_bot` that changes the tool scope: the card lists the tools added and removed; pressing applies exactly what the card showed even if the model's later text says otherwise.
2. `delete_transaction`: the card shows the trade (date, symbol, side, quantity, price) and the position and cash after the deletion; a transaction id from another owner or an already-deleted one is refused without a card.
3. `update_routine` with `every_value: 2, every_unit: hour`: the routine runs every two hours afterwards; values the route rejects are rejected the same way here, with the same reason.
4. `analyze` with `catalog_model`: the card's cost line names the model; a name not in the catalog is refused before a card.
5. A new route added to `app/` without a registry entry fails the test with a message naming the route and telling the developer the two choices.

---

### Task 1: routines, analysis model, model list

- `create_routine` / `update_routine` accept what `POST`/`PATCH /tasks` accept and the operation lacks today: `every_value` + `every_unit` (hour/day/week), `max_runs`, `channel`, the task kind and `skill_id` — read the route's schema and reuse its validation.
- `analyze` accepts optional `catalog_model` (a catalog entry name) and `force` (re-run even if an analysis exists); the card's cost line names the model.
- New read tool `list_models` (owner only): the catalog entries (name, provider, model id, whether a key is set — never the key), the default chat model, and each background role's model. Add to the kernel's `READ_TOOLS`, unnumbered like the other own-state reads, with a progress phrase 「看可用模型」.
- Tests: Review Focus 3 and 4; the model list never contains a key or key length; a guest is not offered `list_models`.

### Task 2: bots, transactions, skills, model settings, channels

New operations (all tier 2):
- `create_bot`, `update_bot` (name, title, description, focus companies, tool scope, model, effort, pinned, hidden, skills) — same validation as `POST`/`PATCH /bots`. Not `delete_bot`.
- `delete_transaction` (by id) — through the portfolio service the route uses; the card per Review Focus 2.
- `manage_skill` with `action` ∈ `enable`, `disable`, `edit` (name, body, output template, allowed tools — same validation as `PATCH /skills/{id}`), `delete` (its own card, says it cannot be undone).
- `set_default_model` (a catalog entry name), `set_model_role` (role, entry name or none) — same as the routes.
- `set_channel_prefs` (mode and channels as `PUT /channels`) — the card says where proactive messages will go from now on.
- Each operation's summary line in the directory, its card text (old → new), and tests for: card content, refusal of invalid input before a card, execution equals the route's effect, guest refusal.

### Task 3: the "nothing slips" check and the confirm-endpoint fix

- `app/kernel/operation_registry.py`: a mapping from `(method, path)` to either `{"operation": name}` or `{"exempt": reason}` for every state-changing route, filled from the inventory (its 92 rows; update the rows this plan covered). Reasons in Chinese, one line each.
- `tests/test_operation_registry.py`: walk `app.main.app.routes` (and any mounted routers); every `POST`/`PUT`/`PATCH`/`DELETE` route is in the registry; every operation named in the registry exists in `act.OPERATIONS`; every `act` operation appears in the registry at least once (or is marked kernel-only). The failure message names the route and the two choices.
- The `/finbot/routines/{id}/confirm` fix per Global Constraints, with tests for: no token → refused; wrong token → refused; right token → works; the bridge or notification caller still works.

### Task 4 (controller)

Full suite once locally. Update the inventory report's covered/gap counts. Box-side checks wait for the box: one real card of each new kind pressed on the shadow database.
