# 5a Alert tiers (异动重新设计) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sentinel's price-move push policy (anchor + re-alert every step, 5-minute moves on for holdings, plan prices re-firing on every crossing) with the tiered policy of design §7.3: measure each move by the stock's own daily σ, group it into three tiers (record / worth knowing / major), say each tier once per direction per day, lock price levels after a crossing, keep 5-minute moves off by default, merge moves the whole market shares, and say what the market did at the same time. Validate by replaying the last weeks of real bars against the 70 alerts actually sent, before it becomes the default.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §7.3 items 1–6 and 8 (item 7, the reason, is 5c: the model is woken for tiers 2–3 through the existing `alert_posted` → `wake` path, which stays as it is). Owner's own rules, preset rules made visible, portfolio rules, multi-day rules: 5b.

**Why (CLAUDE.md):** 21 days, 70 alerts, 38+ on INTC; 15 of 41 readable ones were under 2σ of the stock's own day; a 5-minute 1% move on a 7.5%-σ stock was called 4.5σ; one add price fired 10 times. The rules decide whether to bother the owner, so noise is a first-class defect, as a miss would be. Hard guarantees stay: a stop-price crossing and a ≥4σ move always go out, escalated if unacknowledged.

## Architecture

- `sentinel/` stays stdlib-only and never imports `app`.
- New module `sentinel/tiers.py`: pure functions, no I/O.
  - `measure(...)` → `{sigma_mult, r, direction, market_r, impact_pct}`
  - `tier_of(measure, sensitivity, held, impact)` → 0 record / 1 worth knowing / 2 major
  - `decide(day_state, tier, direction, r, extreme_r, now)` → push or not, and why
  - `level_state(...)` → price-level lock, re-arm, count
  - `group(candidates, market_r)` → merged or single
- `sentinel/main.py`: `alerts_from` / `_price_push` call the new policy when `SENTINEL_ALERT_POLICY=tiers` (the default once the replay passes), else the anchor policy exactly as today. Escalation, night deferral, the merge interval, receipts, digest and `alert_posted` are reused, not rewritten.
- `sentinel/replay.py` + `scripts/sentinel_replay.py`: the replay harness. It runs the policy over stored or fetched 5-minute bars for a date range and writes the alerts it would have sent.
- Day state persists in the existing `price_event` table, extended, or a new `tier_state` table: per (symbol, NY date, direction), the highest tier said, the day's extreme r, and whether a reversal was said. Level locks persist per (symbol, level kind, level price): the last crossing direction, whether armed, and the crossing count today.

## Global Constraints

- **Measures (code only).**
  - `sigma_mult = |price / prev_close − 1| / daily_sigma`. `daily_sigma` comes from the existing 20-day baseline; without it, the fallback is the existing `DAILY_FALLBACK` logic, unit 2%.
  - `market_r`: SPY's move from its previous close at the same minute. Fetched once per poll and cached for the poll; if it is unavailable, omit it.
  - `impact_pct` (holdings only): `shares × (price − prev_close) / total_assets × 100`.
- **Tiers (defaults = 标准).** Sensitivity `quiet / standard / sensitive` is read from the snapshot key `alert_sensitivity`, overridable by the env `SENTINEL_SENSITIVITY`, default `standard`.

  | Tier | quiet | standard | sensitive |
  |---|---|---|---|
  | worth knowing (1): σ multiple ≥ | 2.5 | 2 | 1.5 |
  | major (2): σ multiple ≥ | 5 | 4 | 3 |

  - Major also when the stop price is crossed, or for a holding when `|impact_pct| ≥ 2`.
  - Worth knowing also on the first crossing of the add or target price (and the stop, which is major).
  - Under tier 1 nothing is pushed. A tier-0 move above 1σ is written as a digest line, so the existing digest shows "today's moves that were not sent".
  - Holdings and research-queue symbols use the same tiers. A research-queue symbol has no impact or plan rules.
- **Once per tier per direction per NY date.**
  - The first time a symbol reaches tier ≥ 1 in a direction, push.
  - Afterwards, push again only when (a) the tier rises (1 → 2), or (b) a reversal: after a pushed tier ≥ 1, the move gives back at least half of the day's extreme r, measured from prev_close (say once per day per symbol), or (c) the price crosses to the other side of prev_close and reaches tier ≥ 1 there (that is the other direction, so its own first push).
  - No step re-alerts, no 3% ladders. `MIN_GAP` 10 minutes between pushes on one symbol stays.
- **Gap at the open.** The pre-market or opening print is measured the same way: tier from σ multiple vs prev close. No separate gap rule.
- **Price levels (add / target / stop): lock.**
  - Crossing fires once (tier as above) and locks the level.
  - It re-arms only after the price has moved away from the level by ≥ 0.5 × daily σ (fraction of price; fallback 1%) on the side it came from.
  - A re-armed crossing on the same NY date says 「第 N 次穿过」. The count resets at the next date.
  - A crossing within the lock never fires.
- **5-minute moves: off by default.**
  - Turned on by the snapshot key `short_moves: true` (env `SENTINEL_SHORT_MOVES=on`).
  - When on, a 5- or 15-minute move needs ≥ 0.5 × daily σ (not 4× the bucket's 5-minute σ, and not the 1% floor).
  - Pre-market, the last 5 minutes' volume must also be ≥ 3× the bucket's average.
  - It is tier 1 at most, and also once per direction per day.
- **Moving together.**
  - In one poll, if ≥ 3 symbols push in the same direction and SPY moved the same way by ≥ 1σ of SPY's own daily σ (or ≥ 1% when unknown), send ONE message.
  - It reads: 「大盘同向：标普 +x%；你关注的 N 只 …」 with each symbol's move and tier, holdings first.
  - Otherwise the existing merge-burst behaviour (≥ 3 pushes within 5 minutes) applies unchanged.
- **Every pushed message says, by code:**
  - the move vs prev close and its σ multiple in words (「约 2.3 倍它的日常波动」);
  - for a holding, the impact on total assets;
  - SPY's move at the same time (「同期标普 +0.4%」) when known;
  - which rule fired (「值得知道：超过 2 倍日常波动」 / 「重大：穿过止损价 30.00」 / 「第 2 次穿过补仓价 55.00」).
  - No reason text: the reason is 5c. Do not write 「原因」.
- **Escalation.** Major tier pushes (and any stop crossing) set `escalate=True` for holdings; worth-knowing pushes do not. A rise to major escalates.
- **Unchanged:** splits handling, the filings watcher, earnings alerts, health/forecast jobs, the night rule and digest, receipts, the `alert_posted` queue (payload gains `tier` and `sigma_mult`), the anchor policy under `SENTINEL_ALERT_POLICY=anchor`.
- **Replay harness.**
  - `python -m scripts.sentinel_replay --symbols INTC,NVDA,... --from 2026-11-03 --to 2026-11-25 [--policy tiers|anchor] [--sensitivity standard]`.
  - It fetches 5-minute bars, range 60d with pre/post, and daily bars from Yahoo (the same fetchers), then steps every 5 minutes through each NY session (04:00–20:00).
  - At each step it builds the bars the live loop would have seen, using a fake clock and an in-memory store, and runs `alerts_from` + `flush` with escalation stubbed to collect messages.
  - Positions, plans and total assets come from a JSON file. For the past it is the owner's snapshot at the time; use today's `data/sentinel-config.json` copy for the shape and say so in the output.
  - Output: a CSV/Markdown list `time, symbol, tier, kind, text` and counts per symbol/tier.
  - `--compare-actual <sentinel.db copy>` lines up each actual alert (from the `alerts` table) with what the new policy would have sent within ±30 minutes.
- **Tests:** pure-function tests for `tiers.py`; `alerts_from`/`flush` tests with built bars; flag `anchor` parity (existing sentinel tests pass unchanged with `SENTINEL_ALERT_POLICY=anchor`; set it in those tests' fixtures if the default changes). No network in tests. Run only `tests/test_sentinel_*.py` and new files.

## Tasks

- [ ] T1 `sentinel/tiers.py` + tests: measures, tier table per sensitivity, decide (first, rise, reversal, opposite side, MIN_GAP), level lock and re-arm and count, short-move rule, grouping rule.
- [ ] T2 Day/level state persistence in `sentinel/store.py` (new tables, `CREATE TABLE IF NOT EXISTS`, no change to old tables' meaning) + tests.
- [ ] T3 `sentinel/main.py`: the `tiers` path through `alerts_from` / `_price_push` / `flush`, SPY fetch per poll, message text (`signals.format_tiered`, `format_grouped`), digest lines for tier-0 >1σ, `alert_posted` payload fields; flag. Tests with built bars: INTC-like stock (σ 7.5%): a 1% 5-minute pre-market drop → nothing; −16% day → one tier-1 then one tier-2; NVDA +36% → tier 2 once; add price crossed 5 times in a week → once a day at most, re-armed only after 0.5σ away, 「第 2 次」 when same day; three symbols with SPY −2% → one grouped message.
- [ ] T4 Replay harness + `--compare-actual`; run it locally on fetched bars for 11-03..11-25 (network allowed in the script, not in tests); save the output under `docs/reports/2026-11-stage-5a-replay/`.

## Review Focus

1. A stop-price crossing or a ≥ 4σ move (standard) can never be swallowed by the once-per-day rule, MIN_GAP holding, the lock, or grouping (it is pushed, at worst on the next poll, and escalated for a holding).
2. With `SENTINEL_ALERT_POLICY=anchor` the behaviour and messages are exactly today's.
3. No state leak across NY dates (pre-market belongs to the new date); a restart mid-day does not repeat pushes (state is in sqlite).
4. The grouped message never hides a major tier of a holding (a holding at tier 2 is listed first and the message escalates).
5. Replay output is reproducible and its comparison with the actual 70 alerts is honest (say which actual alerts would not be sent and why).
