# 5c-3a The daily missed-alert check

**Goal:** Every morning (Beijing 07:45) code checks what should have reached the owner since the last check against what did, and the 08:05 brief tells him what was missed, in code-written lines. No model call in the check.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §7.2 「每天自查一次漏报。对照当天应该发生的事（财报日、你设的价位）和实际发出的提醒，漏了就补发并说明。英伟达 11-17 那次就是这样漏的。」; §7.3 「事后复盘」 layer; §7.6 「过滤掉了该说的：靠硬保证和漏报自查兜底」.

**Why this, and why code:** the 11-17 miss is in production right now: `earnings_events` has `NVDA failed 3 skipped_no_first` — the earnings reader failed three times and nobody was told. Whether something was sent is a record the system holds; checking it is code's job, not the model's (CLAUDE.md: 能由代码/系统侧承担的记录不要推给模型).

## 5c-3 slicing

| Slice | What |
|---|---|
| **5c-3a** (this) | daily missed-alert check: earnings and prices; findings ride in the 08:05 brief |
| 5c-3b | 「有用／没用」 on every alert and duty message: Telegram, WeChat, web (list each channel's request format first, per collaboration-rules §4.5) |

## What counts as missed

**Earnings (holdings and the research queue).** In the window (changed after the shadow check: the 11-17 NVDA miss was a research-queue company — a queue company's earnings are only recorded, not pushed, but a reader that failed records nothing):

1. an `earnings_events` row of a held symbol with `status == "failed"` → 「财报解读三次都没做成，没发给你」;
2. an `earnings_events` row of a held symbol still `received` or `analysing` more than 60 minutes after `created_at` → 「收到一个多小时了还没发出」;
3. a sentinel `earnings_seen` row (read-only `data/sentinel.db`) of a held symbol with `detected_at` in the window and no `earnings_events` row with the same accession → 「盯盘程序看到了这份财报，但没交到解读那一步」.

Each earnings finding carries the filing link (`source_url` / the `earnings_seen` URL) so he can open it.

**Prices (the last New York session).** Replay the sentinel's real policy (`sentinel.replay.run_replay`, the snapshot `data/sentinel-config.json`, the live settings) over that session's bars, then compare with the live `alerts` table (read-only) for that New York date:

- a replayed alert counts when its `tier` is 1 or 2 **and it is one of the day's own move alerts** (`daily`, `gap`, `update`, `move`, `reversal`, `merged`). Changed after the shadow check of 11-25: rules, presets and price levels fire once while their condition holds and stay locked across days (`rule_state`, `level_lock`); the replay starts from an empty store, so they came out as five false misses (concentration, 52-week low, portfolio drop) and no real one. Those kinds are not checked in this slice. A tier-1 move also has to clear the worth-knowing line by 0.5 sigma (ANT pre-market at 2.0 and 2.1 sigmas on 11-24 and 11-25: within the 5- vs 1-minute noise);
- it is **missed only if the live table has no alert at all on any of its symbols that New York date** (any kind except `earnings*`). This is deliberately conservative: the replay reads 5-minute bars, the live loop 1-minute bars, so a replayed alert next to a live one on the same symbol is a granularity difference, not a miss (CLAUDE.md: 误报是一等缺陷). What this catches is the sentinel not running, not fetching, or a rule that never fired at all.
- one finding per symbol (the first replayed alert), with its New York time and its first text line.

**Not in this slice:** filings other than earnings (a new 8-K of another kind); research-queue earnings (they are only recorded, by design); the post-market after the check runs (07:45 Beijing is 18:45/19:45 New York, so 18:45–20:00 is not covered).

## Task 1 — the log (`app/duty_selfcheck.py`, new)

Like `app/duty_brief.py`:

```python
class DutySelfcheck(Base):
    __tablename__ = "duty_selfcheck"
    __table_args__ = (UniqueConstraint("owner_hash", "day", name="uq_duty_selfcheck_owner_day"),)
    id BigInteger pk; created_at DateTime(tz) index; owner_hash String(64) index; day String(10)   # Beijing date
    outcome String(16)          # running | done | skipped_off | failed
    reason Text | None
    session String(10) | None   # the New York date the price check covered; None when there was none
    findings JSON default []    # [{"kind": "earnings"|"price", "symbol", "at", "text", "why", "url"?}]
    checked JSON default {}     # {"earnings_events": n, "earnings_seen": n, "price_symbols": [...], "replayed": n, "live": n, "errors": {"earnings": "...", "price": "..."}}
    ms Integer default 0
```

`claim`, `finish`, `get(owner, day)`, `since(owner, after) -> list[dict]` (done rows created after `after`, oldest first), `as_dict`. Register the import next to `duty_brief` in `app/sentinel_api.py`.

## Task 2 — the check (`app/kernel/selfcheck.py`, new; no model)

- `BEIJING`, `ET = ZoneInfo("America/New_York")`, `DUE_AT = (7, 45)`, `LAST_HOUR = 12`, `STUCK = timedelta(minutes=60)`, `WINDOW_FIRST = timedelta(days=14)` (the first check ever reaches back far enough to tell the 11-17 NVDA miss once; every later window starts at the previous done check).
- `due_day(now) -> str | None`: Beijing 07:45 inclusive to 12:00 exclusive.
- `session_day(now) -> date | None`: the New York date of `now` when it is Monday–Friday and New York time is 16:00 or later, else None (weekends, or a check run before the close).
- `held_symbols(snapshot) -> set[str]`: positions with shares.
- `earnings_findings(owner, since, now, held, sentinel_db) -> (list, dict)`: the three earnings rules above; the dict is the counts for `checked`.
- `price_findings(day, snapshot, sentinel_db, fetch=replay.fetch_data) -> (list, dict)`: symbols = held + research queue + owner-rule symbols (as `run_replay` picks them); `data = fetch(symbols)`; `run_replay(data, snapshot, day, day)` in a temp dir; live alerts of that New York date from `sentinel_db` (read-only, `mode=ro`, falling back to `mode=ro&immutable=1` as `replay.compare_actual` does); the rule above. `fetch` is a parameter so tests pass scripted bars.
- `run_once(owner, now, *, day=None, sentinel_db=None, snapshot=None, fetch=None) -> dict | None`: `day = day or due_day(now)`; None → None; existing row → None; claim; mode `off` → `skipped_off`; window `since` = the newest done check's `created_at`, else `now - WINDOW_FIRST`; run the earnings check and the price check, each in its own `try` — a failed check writes its error under `checked["errors"]` and the other still runs; finish `done` with all findings (sorted by `at`). An exception outside both → `failed`. Never raises after the claim.
- Paths: `sentinel_db` defaults to `ROOT / "data" / "sentinel.db"`, `snapshot` to `json.loads(sentinel_bridge.snapshot_path().read_text())`.

## Task 3 — the brief carries the findings (`app/kernel/brief.py`)

- `gather` (or `_run`) also reads `duty_selfcheck.since(owner, since)` and collects their findings (dedupe by `(kind, symbol, at)`).
- `selfcheck_lines(findings) -> str`, code-written, empty when none:

```text
漏报自查（每天收盘后核对，代码写的）：
· {symbol} 的财报（{at}）没发给你：{why}。原文：{url}
· {symbol} 美东 {at}：{text}——按现在的设置应当提醒，但当时没有发出（收盘后用五分钟线重算发现）。
```

- The message becomes `HEAD + body + ("\n\n" + selfcheck_lines) + ("\n\n" + filtered_line)`; with no kept and no held but findings, `HEAD + selfcheck_lines (+ filtered)` with no model call.
- Findings count as content: a window with only findings is not `skipped`.
- `counts` gains `"missed": n`.
- The model is not given the findings: the lines are the system's record.

## Task 4 — the loop (`app/background.py`)

`SELFCHECK_SECONDS = 60`; `run_selfcheck()` like `run_morning_brief` (owner from the login config, `asyncio.run` not needed: `run_once` is sync — make it sync); `("duty-selfcheck", SELFCHECK_SECONDS, run_selfcheck)`; update `tests/test_background.py`.

## Task 5 — replay tool

`scripts/selfcheck_replay.py`, same guards as `scripts/brief_replay.py` (shadow DB `finbot_ruler` only, forced `shadow`): `--day` (Beijing date of the row), `--now` (ISO instant to evaluate as, default now), `--since-hours`, prints the row JSON. It may read the live `data/sentinel.db` and snapshot read-only (the shadow source copy has its own `data/` copy from `ruler_shadow.sh up`; use that by default).

## Tests (`tests/test_kernel_selfcheck.py`, new; `tests/test_selfcheck_replay.py`)

- `due_day` edges (07:44 / 07:45 / 11:59 / 12:00 Beijing); `session_day`: Friday 18:45 ET → Friday; Saturday → None; Tuesday 15:00 ET → None.
- earnings: failed held event → finding with url; a queue (not held) failed event → nothing; `analysing` 61 minutes old → finding, 30 minutes → nothing; `earnings_seen` without an event → finding; with an event of the same accession → nothing; rows before `since` → nothing.
- prices (scripted `fetch` returning bars that make the replay raise a tier-2 move on INTC): no live alert that day → one finding; any live alert on INTC that day (even a different kind) → nothing; a live alert on INTC the day before → still a finding; two replayed alerts on INTC → one finding.
- a price check that raises → `errors["price"]` set, earnings findings still written, outcome `done`.
- second `run_once` the same day → None; mode `off` → `skipped_off`.
- brief: findings only → `HEAD + selfcheck_lines`, no model call; with kept → lines between the body and the filtered line; findings not in the model's messages; `counts["missed"]`.
- the replay tool's guards (mirroring `tests/test_brief_replay.py`).

## Task 6 — check against production data, ship

- On the shadow environment (11-27 backup, its own copy of `data/`): run `selfcheck_replay --day 2026-11-28 --since-hours 400` — the NVDA 11-17 `failed` event must come out as a finding. Read the price check's result for the 11-25 session (`--now` set to 11-25 19:00 ET).
- Full suite on the final commit; ruler; report `docs/reports/2026-11-stage-5c3a.md`; Fable acceptance; release (same archive-swap). First real check: Beijing 11-28 07:45 (covers the 11-27 half day; the 14-day first window tells the 11-17 NVDA miss once).
