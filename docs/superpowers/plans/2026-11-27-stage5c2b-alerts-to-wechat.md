# 5c-2b The sentinel's price alerts reach WeChat too

**Goal:** When the owner's channel preference puts WeChat first (or asks for every channel), each alert the sentinel sends also goes to WeChat, once, at the moment it is sent. The sentinel's own path (stdlib, Telegram, 「收到」, Pushover escalation) is not touched.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §8 (the channel layer); the 5c slicing in `docs/superpowers/plans/2026-11-27-stage5c1-cause-followup.md` (「Sentinel price alerts themselves going to WeChat … kept for 5c-2」). Known since 1e: 「价格提醒仍只到 Telegram」.

**Why here, not in the sentinel:** every alert is already posted to the API (`alert_posted`, for the wake). The API owns the outbox and the channel preference, and the WeChat bridge already sends outbox rows. The sentinel stays stdlib and stays the guaranteed Telegram path.

## When a WeChat copy is made

`channels.prefs(owner)` gives `channels` (ordered) and `mode` (`first` | `all`):

| Preference | Copy? | Why |
|---|---|---|
| `["telegram"]` (the default) | no | Telegram already has it |
| `["telegram", "wechat"]`, `first` | no | WeChat is only the fallback; the sentinel's Telegram send is its own path |
| `["wechat"]` or `["wechat", "telegram"]`, `first` | yes | he reads WeChat first |
| any list with `wechat`, `all` | yes | he asked for every channel |

And never when:
- the event is `deferred` (held over the night: it reaches him with the 08:00 digest and the morning brief);
- WeChat is not available (`channels.available(db, owner, "wechat", bot)` false: no login);
- a copy for that alert id was already made (the sentinel re-posts a night line under the same id; an API restart re-delivers queued events).

## Task 1 — the copy (`app/sentinel_copy.py`, new)

```python
class SentinelCopy(Base):
    __tablename__ = "sentinel_copy"
    owner_hash String(64) pk; alert_id BigInteger pk
    created_at DateTime(tz) default now(UTC)
    outcome String(24)          # queued | skipped_deferred | skipped_unwanted | skipped_unavailable | failed
    group_id Uuid | None        # the outbox group of the WeChat row
```

- `SOURCE = "sentinel"` (fits `String(10)`).
- `wanted(prefs) -> bool` — the table above.
- `copy_to_wechat(owner_hash, event) -> dict`: decide; for `queued`, insert the row first (IntegrityError → return the existing row, nothing queued) then `agent_telegram.enqueue(db, owner, bot.id, agent_telegram.render(bot.name, event["text"]), source=SOURCE, channels=["wechat"])` with the owner's default bot (`agent_bots.ensure_default_bot`), set `group_id` like `wake._deliver` does, commit. `skipped_unwanted` writes no row (the common case; nothing to record). Other skips write their row. Never raises: an exception is logged and returns `{"outcome": "failed"}`.
- Register the import next to `duty_brief` etc. in `app/sentinel_api.py`.

## Task 2 — wiring

- `app/sentinel_api.py` `alert_posted`: after `clean_event`, `await asyncio.to_thread(sentinel_copy.copy_to_wechat, owner, event)` inside a `try` that logs and goes on; then `wake.submit` as now; still 202.
- `app/agent_telegram.py`: `UNCAPPED` gains `"sentinel"` (the sentinel's own alerts were never under the bot's notify cap; the copy is not either).
- `app/channels.py` `fail_over`: a row of source `sentinel` never fails over (Telegram already has the alert from the sentinel itself; a fail-over would be a second Telegram copy). One line plus a comment.
- `frontend/src/backstage-view.mjs` `SOURCES`: `sentinel: "盯盘提醒"`; locale entries (zh-CN list, en-US 「盯盘提醒」 Sentinel alert) if the existing source labels have them.

## Tests

- `tests/test_sentinel_copy.py` (new): `wanted` for every row of the table; a copy queued for `["wechat"]` (one outbox row, channel `wechat`, source `sentinel`, text carries the alert text); none for the default preference; `deferred` → `skipped_deferred` and no outbox row; WeChat unavailable → `skipped_unavailable`; the same alert id twice → one outbox row; a full notify cap does not stop it; an exception inside → `failed`, no raise.
- `tests/test_channels.py`: a closed `sentinel` row does not fail over to Telegram; a closed `notify` row still does.
- The endpoint (`tests/test_sentinel_wake.py` or where `alert_posted` is tested): `alert_posted` calls the copy and still answers 202 when the copy raises; the wake still gets the event.
- Frontend: the `sentinel` source label.

## Ship

Full suite on the final commit; ruler; report `docs/reports/2026-11-stage-5c2b.md`; Fable acceptance; release (archive-swap; new table `sentinel_copy` via `create_all`). The owner's current preference decides whether anything changes for him: with the default (Telegram only) nothing does — say so in the report, and that he turns it on under 设置 → 「主动消息发到哪里」.
