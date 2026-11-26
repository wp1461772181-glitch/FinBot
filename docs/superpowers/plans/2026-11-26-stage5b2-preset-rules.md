# 5b-2 Preset rules made visible and editable; portfolio presets; the rules page; the sensitivity switch

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The system's own rules stop being a black box.

- Each preset rule is listed next to the owner's own rules, marked 「系统默认」. Each one can be turned off or given a new threshold; the stop price and filings stay on as hard guarantees.
- New presets cover what no rule watched before: one holding too big a share of the portfolio, a portfolio-wide day drop, a run of down days, 52-week highs and lows, unusual volume on a holding.
- The owner can set the sensitivity (安静 / 标准 / 灵敏) and the 5-minute moves switch, in chat (a card) or on the web page.
- On a symbol where the owner has a rule of the same kind, the preset of that kind yields.

**Spec:**

- `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §7.3:
  - 「两套规则并行」
  - 「预置规则打算覆盖的方面」
  - item 8 (sensitivity)
- 5b-1: `docs/superpowers/plans/2026-11-26-stage5b1-owner-watch-rules.md` (the rule contract this extends).

**Why (CLAUDE.md):** The defaults decide what bothers the owner, so they must be visible and his to change (准则 2). Any default the system keeps hidden is a hidden rule.

## Contract (the snapshot; all three parts build against it)

The snapshot (`data/sentinel-config.json`) gains:

```json
{
  "alert_settings": {"sensitivity": "standard", "short_moves": false},
  "presets": [
    {"id": "preset:concentration", "preset_key": "concentration", "source": "preset", "scope": "holdings", "symbol": "*",
     "metric": "position_weight", "direction": "above", "levels": [{"threshold": 25, "level": "remind"}],
     "window_days": null, "repeat": "daily", "expires_on": null, "created_on": null,
     "text": "单只持仓占总资产超过 25%：提醒。条件成立时提醒一次，回到 25% 以下后再超过会再提醒。"}
  ]
}
```

- `presets` carries enabled presets only, already resolved with the owner's overrides. Each one is rule-shaped (the 5b-1 contract), plus three fields:
  - `source: "preset"`;
  - `preset_key`;
  - `scope`: `holdings` (every held symbol), `watched` (held + research queue) or `portfolio` (one evaluation for the whole portfolio, `symbol: "*"`).
- `id` is `preset:<key>`.
- `text` is written by code.
- `alert_settings` replaces the sentinel's snapshot keys `alert_sensitivity` / `short_moves`. The sentinel reads `alert_settings` first, then the old keys, then env.

**New metrics** (extend the 5b-1 table; the sentinel measures them, and `describe` / dry run on the API side must use the same meaning):

| metric | measured | threshold | direction | kind |
|---|---|---|---|---|
| `portfolio_day_change` | Σ holdings shares × (price − prev close) / (total assets − that Σ) | % | down / up / either | change (once per level per day) |
| `down_days` | consecutive completed trading days with close < previous close, plus today if price < prev close now | days (integer ≥ 2) | down | state (edge) |
| `high_52w` | price ≥ the highest close of the last 252 completed trading days | threshold ignored (0) | above | state (edge) |
| `low_52w` | price ≤ the lowest close of the last 252 completed trading days | threshold ignored (0) | below | state (edge) |

- `portfolio_day_change` is only valid with scope `portfolio`. The others take any symbol scope, and owner rules may use them on a single symbol too.

**Preset catalog (defaults; code, `app/watch_presets.py`)**

| key | scope | metric | direction | levels (default) | editable |
|---|---|---|---|---|---|
| `concentration` | holdings | position_weight | above | 25 remind | on/off, threshold |
| `portfolio_drawdown` | portfolio | portfolio_day_change | down | 3 remind, 5 urgent | on/off, thresholds |
| `down_streak` | watched | down_days | down | 5 remind | on/off, threshold |
| `new_high_52w` | watched | high_52w | above | 0 remind | on/off |
| `new_low_52w` | watched | low_52w | below | 0 remind | on/off |
| `volume_surge` | holdings | volume_ratio | above | 3 remind | on/off, threshold |

Listed but not editable here:

- the σ day-move tiers (governed by sensitivity);
- the 5-minute moves (governed by `short_moves`);
- the plan prices (edited via the position plan);
- the stop price and filings (hard guarantees: 「这条是硬保证，不能关」).

**Yielding:** for a symbol where the owner has an enabled rule with the same metric, the preset with that metric does not apply to that symbol. For `day_change` the 5b-1 direction-aware override already applies. Owner rules never make the stop price or filings yield.

**Messages from presets (sentinel):**

- 「【系统默认·提醒】INTC 占你总资产 44.2%，超过 25%。 / 规则：单只占比过高（系统默认；可以在「它眼中的你」页面关掉或改门槛）」
- For the portfolio: 「【系统默认·加急】你的组合今天跌 5.3%（-4,312 美元）。…」
- Kind `preset`. The `alert_posted` payload carries `preset_key`.

**Routes (owner only; the web page uses them directly, as an owner's own action; chat goes through cards):**

- `GET /agent-chat/watch` → `{"rules": [...], "presets": [...], "settings": {...}}`.
  - Each owner rule: `{id, symbol, metric, direction, levels, text, status, last_fired, overrides_default}`.
  - Each preset: `{key, title, text, enabled, levels, editable, hard_guarantee, applies_to, yields_on: [symbols]}`. A non-editable preset has `levels: null`.
  - `settings`: `{sensitivity, short_moves, thresholds: {quiet, standard, sensitive}}`.
- `PATCH /agent-chat/watch-presets/{key}` with body `{enabled?, levels?}` → the preset row. An invalid key or a non-editable preset → 400 with a Chinese reason.
- `PUT /agent-chat/alert-settings` with body `{sensitivity?, short_moves?}` → the settings.
- `DELETE /agent-chat/watch-rules/{id}` (exists).
- `POST /agent-chat/watch-presets/{key}/reset` → back to the default.

## Part 1 — API (`.claude/worktrees/s5b2-api`, branch `claude/stage5b2-api`)

- `app/watch_presets.py`:
  - the catalog;
  - table `watch_preset_overrides(owner_hash, preset_key, enabled, levels JSON, updated_at)`, pk (owner_hash, preset_key);
  - `resolved(owner)`;
  - `set_override(owner, key, enabled=None, levels=None)`;
  - `reset(owner, key)`;
  - validation reuses `watch_rules.validate` for the levels shape and per-metric directions.
- `app/watch_rules.py`: validate, describe and dry run for the four new metrics.
  - Dry run for `portfolio_day_change`: today's shares × daily moves of each holding / today's total assets adjusted like position_weight.
  - Dry run for `down_days`: from daily closes.
  - Dry run for `high_52w` / `low_52w`: needs 252 days of `market_prices`; otherwise 「历史行情不够一年，试跑不了」.
  - Owner rules may use `down_days`, `high_52w` and `low_52w` on a symbol. `portfolio_day_change` is preset-only for now; an owner rule on it is refused with a reason.
- Table `alert_settings(owner_hash pk, sensitivity, short_moves, updated_at)`. Defaults: standard, false.
- `app/sentinel_bridge.py`: `alert_settings` and `presets` sections. On a read failure keep the previous file's values (as the 5b-1 rules section does).
- Kernel `act` (tier 2 cards):
  - `set_watch_preset` takes `{key, enabled?, levels?}`. The card shows the old and new text and a dry run where one exists.
  - `set_alert_settings` takes `{sensitivity?, short_moves?}`. The card shows the threshold table for the chosen sensitivity (2/4 → 1.5/3, …) in words.
  - Directory summaries say the stop price and filings are hard guarantees and cannot be turned off.
- `list_watch_rules` (read tool) and the memory overview read from the same `GET /agent-chat/watch` builder (one function, `watch_view(owner)`).
- Routes as above, with registry entries: the PATCH/PUT/POST routes map to the act operations.
- Tests:
  - catalog defaults;
  - overrides and reset;
  - validation and describe for the new metrics;
  - dry runs on built rows;
  - snapshot shape equals `tests/fixtures/watch_presets_contract.json`, which holds the resolved default presets plus `alert_settings`;
  - act cards;
  - routes, owner only;
  - operation registry;
  - list output.

## Part 2 — sentinel (`.claude/worktrees/s5b2-sentinel`, branch `claude/stage5b2-sentinel`)

- `sentinel/rules.py`: `portfolio_day_change`, `down_days`, `high_52w`, `low_52w` (measure + `STATE_METRICS` membership as in the table).
- Daily history (the 5b-1 `rules_daily` cache) extends to `1y` for symbols needing 52-week or down-days data, fetched once per NY date.
- Presets: expanded per scope at each poll.
  - `holdings` → each held symbol; `watched` → held + queue.
  - `portfolio` → one evaluation per poll after all symbols, using the poll's prices for every holding. It measures None if any holding's price is missing or stale.
  - State keys include the preset key and the symbol, so each symbol has its own edge state.
- Yielding as in the contract.
- Messages as in the contract. Kind `preset`; never merged or held. `urgent` escalates; `remind` follows the night rule (into the morning digest).
- Settings: read `alert_settings` first, then the old keys, then env.
- Replay: honours `presets` and `alert_settings` in the snapshot. Run it over 11-03..11-25 with the default presets and report counts per preset; save the output under `docs/reports/2026-11-stage-5b2-replay/`.
- Tests:
  - each new metric (incl. missing data → None);
  - a preset expanded per holding;
  - a portfolio preset;
  - yield when the owner has the same metric on the symbol;
  - a preset never blocks a stop or a filing;
  - edge state per symbol;
  - messages;
  - settings precedence;
  - the contract fixture accepted. Write `tests/fixtures/watch_presets_contract.json` from this plan; the coordinator reconciles it with Part 1's copy.

## Part 3 — web (`.claude/worktrees/s5b2-web`, branch `claude/stage5b2-web`)

- On the memory page, 「它眼中的你」 → 「它在帮你盯的」 (`frontend/src/app/assistant/memory/WatchPanel.tsx` and its API client) shows four parts:
  1. **你定的规则:** each with its text, status (生效 / 已过期 / 已完成) and last fired, a 「删除」 button (plain confirm), and a note on the default it overrides.
  2. **系统默认:** each preset with title, text and on/off switch, plus a threshold edit where editable. Hard guarantees show 「硬保证，不能关」 instead of a switch, with a 「恢复默认」 link when changed. `yields_on` reads 「对 INTC 让位给你的规则」.
  3. **灵敏度:** 安静 / 标准 / 灵敏 as a segmented control, with the σ numbers in words below; the 5-minute moves switch.
  4. A line: 「在对话里也可以说，比如『英特尔跌 8% 提醒我』。」
- Uses `GET /agent-chat/watch`, `PATCH /agent-chat/watch-presets/{key}`, `POST …/reset`, `PUT /agent-chat/alert-settings` and `DELETE /agent-chat/watch-rules/{id}` exactly as in the contract. Optimistic only where reverting is trivial; on error, show the server's Chinese reason.
- i18n keys for every string (zh-CN, en-US); `npm run test:i18n` clean.
- Shots fixtures for the new endpoints; screenshots at 1440 and 390 of the memory page with rules + presets.
- Pure-function tests for formatting the σ numbers and the status labels.
- Frontend checks run in a scratch copy, because the repo's `frontend/node_modules` is a broken symlink. Use `git archive HEAD | tar -x` into a temp directory, then `npm ci`, then `npm run test:i18n`, `npx tsc -b` and `npm run build`. For shots: `tools/shots` `npm ci`, then `node run.mjs --dist ../../dist --pages <yours> --widths 390,1440 --strict` after building with `VITE_API_BASE_URL=https://api.example.test VITE_BASE_PATH=/`.

## Global Constraints

- The model fills fields only; code writes all texts.
- Chat changes go through cards; the web page uses the routes directly, as the owner's own action.
- The stop price and filings can never be turned off or yield.
- Old engine unchanged.
- TDD.
- Run only related tests, never the whole suite.
- No network in tests.
- Check the branch before each commit.

## Review Focus

1. Presets produce the same meaning in the card or dry run and in the sentinel (the new metrics especially).
2. Default counts are not noisy. Use the replay over three weeks with the owner's holdings; if a preset fires more than about once a week on average, say so.
3. Hard guarantees are untouched.
4. The web page cannot turn off a hard guarantee, and the routes refuse it too.
