# 5c-1 A move worth knowing comes with its cause; the duty starts sending

**Goal:** When the sentinel raises a 「值得知道」 or 「重大」 alert, the kernel (already woken for every alert) looks for why, and tells the owner what it found — or plainly that it found nothing. Then the duty is switched from `shadow` to `on`, so those messages actually reach him (through the outbox, so WeChat gets them too).

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md`

- §7.2 「异常必有解释」「重要的事分两句说」「它记得自己说过什么」
- §7.3 item 7 「原因由它来查，只在值得知道和重大两级才叫醒它」

**Why (CLAUDE.md):** 准则 3 — the model is good at reading filings and news and saying why something moved; the system today never asks it to. The rule stays in the prompt the model reads, not in a hidden check: no code refuses a decision because a cause is missing (准则 1).

## 5c slicing (why this order)

| Slice | What | Why here |
|---|---|---|
| **5c-1** (this) | cause follow-up for tier ≥ 1; duty `on` | Every piece it needs is live (5a tiers on the event, wake turns, the outbox). Five shadow wakes 11-24..11-26 judged sensibly, so sending is the next step. |
| 5c-2 | the 08:00 brief written by the kernel: the night's record lines, its own `digest` decisions, 「今天替你过滤了 N 条」 from `record`/`ignore` | needs 5c-1's messages to be live so the brief can say what was already told |
| 5c-3 | daily missed-alert self-check; 「有用／没用」 on every alert (web, Telegram, WeChat) | needs 5c-2's brief to report into |

Sentinel price alerts themselves going to WeChat (the sentinel sends Telegram directly) is kept for 5c-2, where the brief already goes through the outbox.

## Deliberately not done

- **The sentinel's alert does not say 「原因还在查」.** §7.3 item 7 suggests it. The sentinel cannot know that the wake will run (the API may be down, the day's duty cap may be reached, the model may fail), so it would promise a follow-up that sometimes never comes. The follow-up message names the alert it is about instead.
- **No code check that a cause was given.** The prompt tells the model what the owner needs; `reason` already records why it chose otherwise.

## Task 1 — the wake knows the tier and is asked for the cause

Files: `app/kernel/wake.py`, `app/kernel/prompt.py`, `tests/test_kernel_wake.py`.

1. `wake._facts`: the relation gains `tier_label`:
   - `"值得知道"` when `event.get("tier") == 1`, `"重大"` when `== 2`;
   - absent (key not present) otherwise, including a missing, bool or non-int `tier`.
   - Code it as a small module-level dict `TIER_LABELS = {1: "值得知道", 2: "重大"}` and a guard `isinstance(tier, int) and not isinstance(tier, bool)`.
2. `prompt.wake_system_text()`: add one section **after** 「四个选择」 and **before** 「怎么做」, exactly:

```text
异动的原因
- 「用户与这件事的关系」里有 tier_label（值得知道或重大）时，他最想知道的是为什么。先用读工具查这只股票最近的公告和新闻；合并提醒（有 members）就查整组，看是不是板块或大盘一起动。
- 查到了原因，就选 tell_now：第一句说是哪条提醒（股票、涨跌），第二句说原因和出处（哪天的哪份公告或哪条新闻）。再说这对他意味着什么。
- 查过了还是没找到明确原因，也选 tell_now，直说查了哪些、没找到，不要猜。
- 只有「最近已经告诉过他的」里已经讲过同一件事的原因、而且没有新进展时，才可以不发。
```

3. Nothing else in the prompt changes. `decide` does not change.

Tests (add to `tests/test_kernel_wake.py`, following the file's existing `env` fixture and helpers):

- `tier_label` is `值得知道` for tier 1 and `重大` for tier 2 in the system block the model receives;
- no `tier_label` key for an event without tier, with `tier=0`, with `tier=True`, with `tier="2"`;
- the system text contains the heading 「异动的原因」 and it comes after 「四个选择」 and before 「怎么做」.

## Task 2 — shadow replay (Claude, on the box's shadow environment)

Run the wake on the shadow environment for real past alerts and read the messages:

| alert | what | expect |
|---|---|---|
| 59 | NVDA 盘前 +19.5% (4.9σ), 11-23 | tell_now with the cause found in news/filings |
| 63 | TSLA +12.5% (3.1σ), 11-23 | tell_now with cause or 「没找到」 |
| 65 | META +7.1% (3.0σ), 11-23 | same |
| 68 | INTC -8.5% (1.0σ), 11-25 (an `update`; no tier field in the old payload) | as before: no cause section applies |

The old alerts predate 5a and carry no `tier`; the replay sets `tier` (and `sigma_mult`) on the event by hand for 59/63/65 and leaves 68 as it was.

Record per alert: decision, whether a cause is named, its source, ms, model calls. Report in `docs/reports/2026-11-stage-5c1.md`.

## Task 3 — ship

1. Full suite on the final commit; ruler once.
2. PR, merge, archive-swap release as before (backup first).
3. On the box: `FINBOT_DUTY_MODE=on` in `/opt/finbot/src/.env`, restart the API only. Rollback: set it back to `shadow` and restart.
4. Tonight (Beijing 22:30, US half day) is the first real session: read `duty_log` and the outbox afterwards.
