# 5b-1 Owner watch rules (你自己定的盯防规则) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner says in chat when to be told, e.g. 「英特尔涨跌 10% 提醒我，20% 加急」. The kernel turns the sentence into one explicit, code-checkable rule and puts it on a confirmation card. The card shows the system's reading of the rule (written by code from the fields) and a 30-day dry run (「按这条规则，过去 30 天会提醒你 3 次：11-05、11-17、11-23」). Nothing takes effect until the owner presses. The sentinel then checks the rule every minute without a model. 「你现在帮我盯着什么」 lists the rules, and each rule can be changed or deleted in one sentence. A symbol with an owner day-move rule no longer gets the default σ-tier day-move alerts. Hard guarantees (stop price, filings) are untouched.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §7.3「你自己定的规则优先」 and 「两套规则并行」 (owner side only). The 5b-2 slice covers: preset rules made visible and editable, portfolio presets, the web page, and the sensitivity switch.

**Why (CLAUDE.md):**
- The code, not the model, writes the rule's plain-language reading and the dry run. The model only fills structured fields; it never writes the card's description, so it carries no form-filling burden and the card cannot drift from what is checked.
- A condition that needs reading content is not turned into a fake rule: the model keeps it as a standing instruction that the duty judgment reads.
- Data the system does not have is said plainly.

## The rule (the one interface both halves share)

Stored server-side; sent to the sentinel in the snapshot as `rules: [Rule, ...]`, enabled rules only.

```json
{
  "id": "uuid",
  "symbol": "INTC",
  "metric": "day_change",
  "direction": "either",
  "levels": [{"threshold": 10, "level": "remind"}, {"threshold": 20, "level": "urgent"}],
  "window_days": null,
  "level_price": null,
  "repeat": "daily",
  "expires_on": null,
  "created_on": "2026-11-26",
  "text": "英特尔相对昨收涨或跌达到 10%：提醒；达到 20%：加急。每天每档一次。"
}
```

**Field meanings**

- `symbol`: an uppercase ticker.
- `levels`: 1 or 2 entries, thresholds ascending, at most one `urgent`.
- `text`: written by code (`watch_rules.describe(rule)`), never by the model.

**Metrics** (what is measured; thresholds in the unit shown):

| metric | measured | threshold unit | direction values |
|---|---|---|---|
| `day_change` | price / prev close − 1 | % | up / down / either |
| `open_change` | price / today's regular-session open − 1 (regular session only) | % | up / down / either |
| `cost_change` | price / position avg cost − 1 (holdings only) | % | up / down / either |
| `n_day_change` | price / close `window_days` trading days ago − 1 (`window_days` 2–60) | % | up / down / either |
| `price` | the price | USD | above / below |
| `volume_ratio` | today's regular-session volume so far / (20-day average daily volume × elapsed fraction of the regular session, floor 0.1); regular session only, not before 10:00 ET | × | above |
| `position_pnl` | shares × (price − prev close), today's P&L of the holding | USD | up (gain) / down (loss) / either |
| `position_weight` | position value / total assets | % | above / below |

**Repeat**

- `daily`: each level fires at most once per NY date.
- `once`: each level fires once ever, and the rule disables itself after its highest level fired.
- `expires_on`: the date after which it is no longer checked.

**Levels**

- `remind` is a tier-1 push.
- `urgent` is a tier-2 push with `escalate=True`. The owner asked for urgency, so it escalates in either direction.

## Two halves (separate worktrees; the JSON above is the contract)

### Half A — API (`.claude/worktrees/s5b1-api`, branch `claude/stage5b1-api`)

- New table `watch_rules`:
  - columns: `id`, `owner_hash`, every field above, `enabled`, `source` (`'owner'`), `quote` (the owner's own words), `created_at`, `updated_at`, `fired_once` (JSON, for `repeat=once`, written back by the sentinel bridge if needed, else ignored in A);
  - created by `Base.metadata.create_all`.
- New module `app/watch_rules.py`:
  - `validate(fields)`: shape, ranges and direction per metric; raises `WatchRuleError(code, Chinese reason)`. A `cost_change` / `position_*` rule on a symbol that is not a holding is refused with a reason.
  - `describe(rule)` → the Chinese text.
  - `dry_run(owner, rule, days=30)` → `{"hits": [{"date", "level"}], "covered_days", "note"}`. It uses `market_prices` daily rows:
    - `day_change`, `open_change`: daily high/low vs prev close/open;
    - `price`: high/low vs the level;
    - `n_day_change`: close vs close N rows before;
    - `volume_ratio`: daily volume / 20-day average;
    - `position_*`: today's shares × daily moves, and total assets taken as today's;
    - `cost_change`: high/low vs the current avg cost.
    - At most one hit per level per day.
    - With under 10 days of rows: `note = "没有足够的历史行情，试跑不了"`.
  - `list_rules(owner)`, `create(owner, fields, quote)`, `update(owner, id, fields)`, `delete(owner, id)` (soft: `enabled=false` + `deleted_at`). Every write refreshes the sentinel snapshot (`sentinel_bridge.refresh_sentinel_snapshot`).
- `app/sentinel_bridge.py`: the snapshot gains `rules` (enabled, not expired), each as the JSON contract above.
- Kernel `act` operations (tier 2, so each goes on a confirmation card): `set_watch_rule` (create, or update when `rule_id` is given) and `delete_watch_rule`.
  - The card body is `describe(rule)` + the dry-run line + 「点确认后生效；哨兵每分钟检查，不用模型。」. `quote` must be the owner's words of this turn (the existing remember-style check).
  - The operation directory summary tells the model:
    - which metrics exist;
    - that a condition needing content (news, policy) is not a rule: remember it as an `instruction` instead, and the duty judgment reads it;
    - that options, short interest and ratings have no data, so say the system cannot watch them.
- Read tool `list_watch_rules` in `READ_TOOLS`: the owner's rules (id, text, created_on, last fired if known) plus the defaults that apply today, each marked 「系统默认」.
  - Defaults: the σ tiers with the current sensitivity, the plan prices, and the 5-minute moves on/off.
  - The defaults list is static text from code; 5b-2 makes it editable.
  - A symbol with an owner `day_change` rule says 「默认的涨跌分级对它不生效」.
- API routes `GET /agent-chat/watch-rules`, `POST /agent-chat/watch-rules`, `PATCH /agent-chat/watch-rules/{id}`, `DELETE /agent-chat/watch-rules/{id}` (owner only). Registry entries in `app/kernel/operation_registry.py`.
- Old engine: unchanged (kernel-only operations, `KERNEL_ONLY`).
- Memory overview / export (`app/memory_overview.py` watch section): list owner rules with their text.
- Tests: validation per metric, `describe` texts, `dry_run` on built `market_prices` rows (incl. the not-enough-data note), act card content and flag-free behaviour, snapshot `rules` shape equals the contract, operation registry test passes, `list_watch_rules` output.

### Half B — sentinel (`.claude/worktrees/s5b1-sentinel`, branch `claude/stage5b1-sentinel`)

- `sentinel/` stays stdlib-only.
- The poll list adds the symbols of rules that are neither held nor queued.
- New `sentinel/rules.py`, pure:
  - `measure(rule, ctx)` → value or None (ctx: price, prev_close, today's open, avg_cost, closes by trading day, today's cumulative regular volume, 20-day avg daily volume, session elapsed fraction, shares, total_assets);
  - `crossed(rule, value)` → the highest level reached, or None;
  - direction handling as in the table.
- `sentinel/main.py`:
  - Each poll evaluates the owner's rules for the symbol, keeping state in a new store table `rule_state(rule_id, ny_date, level, fired_at)`.
  - A level fires once per NY date (`daily`) or once ever (`once`).
  - A rise from remind to urgent the same day fires the urgent level.
  - Messages: 「【你的规则·提醒】/【你的规则·加急】INTC 较昨收跌 10.4%，现价 35.84。 / 按你 11-26 定的规则：<text>」.
  - Kind `rule`.
  - Urgent → `escalate=True`.
  - The `alert_posted` payload gains `rule_id`.
  - Rule pushes are never merged into group messages and never held by MIN_GAP (the owner asked for exactly this).
- Class override: when a symbol has an enabled owner rule with metric `day_change`, the default σ-tier day-move pushes (tiers policy) for that symbol are not sent. The digest `record` row is still written. Unaffected:
  - plan price levels (incl. stop);
  - the 5-minute rule;
  - filings;
  - other symbols.
- Daily closes for `n_day_change`: fetch `1d` / `3mo` once a day per symbol that has such a rule (cached with the baseline).
- Avg daily volume for `volume_ratio`: from the same daily bars.
- Replay (`sentinel/replay.py`): snapshot `rules` are honoured, so a rule can be replayed.
- Tests: each metric and direction; once per day per level; remind→urgent same day; `once` repeat; expiry; class override (a `day_change` rule silences default tiers for that symbol only; the stop still fires); a rule on a non-held, non-queued symbol is polled; messages; `anchor` policy also evaluates rules (rules are independent of the default policy).

## Global Constraints

- The model never writes the rule's description or the dry-run text; code does.
- A rule is created only through the card (tier 2); the owner's typed 「同意」 never confirms.
- Run only the tests of files you touch; check the branch before each commit; WIP-commit before RED; no network in tests; no real model calls.
- Comments in English, user-facing text in Chinese.

## Review Focus

1. The card's text and dry run match what the sentinel will check, for every metric. Same thresholds, same direction semantics, same reference price.
2. An owner rule can never silence a stop-price crossing or a filing alert.
3. A rule whose data is missing (no avg cost, no daily history, pre-market for `volume_ratio`) measures None and never fires falsely. Saying so belongs in the dry run, not in a live false alarm.
4. Snapshot `rules` from Half A is accepted unchanged by Half B (contract test on both sides with the same fixture JSON).
