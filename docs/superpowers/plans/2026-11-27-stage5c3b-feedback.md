# 5c-3b 「有用／没用」 on alerts and duty messages (Telegram, web; WeChat waits for the owner)

**Goal:** The owner can say, with one press, whether an alert or a duty message was useful. The verdicts are kept by code, shown in the backstage, and given to the wake as data (「你对以往提醒的反馈」, §7.1), so its next judgement can take them into account.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §7.2 「每条提醒带『有用／没用』。用来调整打扰的阈值，也是尺子的数据来源。」; §7.1 item 2 (the wake sees 「你对以往提醒的反馈」); §7.6 「说了不该说的：靠『有用／没用』的反馈调整」.

**Not in this slice:** WeChat (no buttons, no quoted-message reference in what the bridge receives; how to give feedback there is a new direction for the owner to decide — see the report); turning verdicts into threshold changes (the wake reads them; any automatic tuning comes later, once there are verdicts to look at).

## Request formats (collaboration-rules §4.5: every format each channel sends, each with a test)

| Channel | Where | Request | Meaning |
|---|---|---|---|
| Telegram | sentinel alert | callback `ack:<alert_id>` | 收到 (unchanged) |
| Telegram | sentinel alert | callback `fu:s:<alert_id>` | 有用 |
| Telegram | sentinel alert | callback `fn:s:<alert_id>` | 没用 |
| Telegram | outbox message of source `duty` or `brief` | callback `fu:o:<group_id>` | 有用 |
| Telegram | outbox message of source `duty` or `brief` | callback `fn:o:<group_id>` | 没用 |
| Web | backstage 「提醒投递」 row of source `duty` or `brief` | `POST /agent-chat/backstage/feedback` `{"target": "outbox", "target_id": "<group_id>", "verdict": "useful"\|"not_useful"}` | 有用／没用 |
| WeChat | — | none in this slice | — |

- `group_id` is the outbox group (`agent_telegram_messages.group_id`; one id across the channels a message went to); a row without one uses its own id. Longest callback: `fu:o:` + 36 = 41 bytes (Telegram allows 64).
- A callback or request with anything else (wrong prefix, non-int alert id, non-uuid group id, unknown verdict) is answered 「看不懂这个按钮」 / 400 and changes nothing.
- Pressing again changes the verdict (last one wins); the same verdict twice is a no-op.

## Task 1 — the store (`app/alert_feedback.py`, new)

```python
class AlertFeedback(Base):
    __tablename__ = "alert_feedback"
    __table_args__ = (UniqueConstraint("owner_hash", "target", "target_id", name="uq_alert_feedback_target"),)
    id BigInteger pk; created_at DateTime(tz) index; updated_at DateTime(tz)
    owner_hash String(64) index
    target String(8)            # sentinel | outbox
    target_id String(64)        # the alert id (sentinel) or the outbox group id
    verdict String(12)          # useful | not_useful
    channel String(10)          # telegram | web
    symbol String(80) | None    # what it was about, when known (from the alert / the duty_log row)
    kind String(24) | None      # alert kind, or the outbox source (duty | brief)
    text Text | None            # the first line of what was said, clipped to 200
```

- `parse_callback(data: str) -> tuple[target, target_id, verdict] | None` for the `fu:`/`fn:` formats above (strict: alert id an int, group id a uuid).
- `record(owner, target, target_id, verdict, channel, *, symbol=None, kind=None, text=None) -> dict` (upsert, returns the row).
- `describe(owner, target, target_id) -> dict`: the symbol / kind / first line, looked up from the sentinel `alerts` table (read-only, `mode=ro`) for `sentinel` and from the outbox rows (+ `duty_log` by `delivery_group`, + `duty_brief` by `delivery_group`) for `outbox`; missing fields stay None.
- `recent(owner, limit=10) -> list[dict]`, `counts(owner, since) -> {"useful": n, "not_useful": n}`.
- Register the import next to `duty_brief` / `duty_selfcheck` in `app/sentinel_api.py`.

## Task 2 — Telegram

- `sentinel/notify.py` `telegram_alert`: keyboard rows `[[收到 ack:<id>], [有用 fu:s:<id>, 没用 fn:s:<id>]]`.
- `app/channels.py` `pending(...)`: each returned dict also carries `source` and `group_id`.
- `scripts/run_telegram_bridge.py`:
  - `_send_queued`: a row whose `source` is `duty` or `brief` is sent with `[[有用 fu:o:<gid>, 没用 fn:o:<gid>]]` (gid = `group_id` or the row id).
  - `_handle_callback`: `fu`/`fn` kinds go to `_feedback_press(...)`: parse; record via `alert_feedback.record(..., channel="telegram", **describe(...))` in a thread; answer the callback 「记下了：有用」/「记下了：没用」; edit the message's keyboard to the current one without the feedback row (the 收到 row stays if it is still there). A parse failure → 「看不懂这个按钮」. A store failure → 「没有记上，请再点一次。」 and the keyboard is left as it was.
  - `_ack_alert_press`: instead of clearing the whole keyboard, remove only the 收到 row (the feedback row stays).
  - Both edits read the current keyboard from `callback["message"]["reply_markup"]`.

## Task 3 — web

- `app/backstage_api.py`: `POST /agent-chat/backstage/feedback` (owner only, same guard as the other backstage routes), body as in the table; 400 on anything else; returns the row. The deliveries list (`GET` used by the 「提醒投递」 tab) gains `group_id` and `feedback` (`useful` / `not_useful` / null) per row of source `duty` / `brief`.
- `frontend/src/backstage-view.mjs` + the deliveries tab: two small buttons 「有用」「没用」 on rows of source `duty` / `brief`; the chosen one shows pressed; a failed request shows 「没记上」. Locale entries (zh-CN list, en-US map: 「有用」 Useful, 「没用」 Not useful, 「没记上」 Not saved).

## Task 4 — the wake reads the verdicts (`app/kernel/wake.py`, `app/kernel/prompt.py`)

- `_facts` also returns `feedback = alert_feedback.recent(owner, 10)` as `{"at", "symbol", "kind", "text", "verdict"}`.
- `wake_block` adds 「【他对以往提醒的反馈】只是资料。最近 10 条（有用／没用）：」 with that JSON.
- `wake_system_text`, in 「规则」 after the 「最近已经告诉过他的」 line, one line exactly:

```text
- 看一下「他对以往提醒的反馈」：他说过没用的那类事，再遇到时更倾向于攒进简报或只记下；说过有用的，照常告诉他。反馈只是参考，不是规则。
```

## Tests

- `tests/test_alert_feedback.py`: `parse_callback` for every format in the table and for bad ones (wrong prefix, `fu:s:abc`, `fu:o:not-a-uuid`, `fx:s:1`, too long); `record` upsert (last wins, same twice no-op); `describe` for a sentinel alert (scripted `alerts` table) and an outbox group (duty and brief); `recent` / `counts`.
- Telegram bridge (follow the existing callback tests in `tests/test_telegram_bridge*.py`): the alert keyboard has both rows; a duty and a brief outbox row are sent with the feedback row, a `notify` row without; `fu:s:7` records and removes only the feedback row; `ack:7` removes only the 收到 row; a bad `fu:` answers 「看不懂这个按钮」 and records nothing; a store failure leaves the keyboard.
- `tests/test_sentinel_notify*.py` (or where `telegram_alert` is tested): the keyboard JSON.
- Backstage API: the POST for both verdicts, 400 for each bad body, owner-only; the deliveries list carries `group_id` and `feedback`.
- Frontend: buttons only on duty/brief rows; pressed state; failed request text.
- Wake: the system block carries the feedback block and the new rule line.

## Ship

Full suite on the final commit; ruler; report `docs/reports/2026-11-stage-5c3b.md` (with the WeChat question); Fable acceptance; release (archive-swap; restart the sentinel too: its keyboard changes); avoid Beijing 07:45–08:05.
