"""Escalation of alerts nobody acknowledged (Task 12).  Stdlib only; never imports ``app``.

Day (Beijing 08:00-24:00): the alert goes to Telegram with a 「收到」button.  A fall on a holding that is still
unacknowledged a minute later becomes a Pushover emergency (rings every 60 s for 30 minutes); the receipt is
polled so an acknowledgement on the phone counts, and a Telegram acknowledgement cancels the receipt.  An
earnings alert nobody acknowledged makes the fall escalate at once.  Without Pushover the alert is resent on
Telegram every 5 minutes, at most 3 times.

Night (Beijing 00:00-08:00): only two things ring at once - an earnings follow-up judged down with high
confidence, and a fall on a holding that is at least 10% of total assets.  Everything else is held and sent as
one digest at 08:00.

Alerts are sent straight from here: they never pass a bot's notify queue, so ``daily_notify_cap`` cannot hold one back.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from .store import Store

logger = logging.getLogger("sentinel.escalation")

BEIJING = timezone(timedelta(hours=8))
NIGHT_END_HOUR = 8
ESCALATE_AFTER = 60.0
RESEND_EVERY = 300.0
MAX_RESENDS = 3
NIGHT_WEIGHT_PCT = 10.0
NIGHT_UPDATE_STEPS = 2.0          # at night a worsening update must travel two steps to ring
RETRY_EVERY = 60.0                # a message Telegram did not accept is tried again, for this long
RETRY_WINDOW = 30 * 60.0
PRICE_KINDS = "('short', 'daily', 'gap', 'update', 'merged')"


def is_night(ts: float) -> bool:
    return datetime.fromtimestamp(ts, BEIJING).hour < NIGHT_END_HOUR


def rings_at_night(alert: dict) -> bool:
    if alert.get("members"):
        return any(rings_at_night(member) for member in alert["members"])
    if alert.get("kind") == "earnings_followup":
        return alert.get("bias") == "down" and alert.get("confidence") == "high"
    if not (alert.get("escalate") and alert.get("held") and (alert.get("weight_pct") or 0) >= NIGHT_WEIGHT_PCT):
        return False
    trigger = alert.get("trigger") or "T0"
    if trigger == "T0":
        return True
    return trigger == "T1" and (alert.get("steps") or 0) >= NIGHT_UPDATE_STEPS


class Escalator:
    def __init__(self, store: Store, channels, clock: Callable[[], float] = time.time) -> None:
        self.store, self.channels, self.clock = store, channels, clock

    # --- a new alert ------------------------------------------------------------------------------
    def raise_alert(self, snap: dict, alert: dict) -> int:
        now = self.clock()
        night = is_night(now)
        ring = rings_at_night(alert)
        hold = night and not ring
        event_date = alert.get("event_date")
        if hold and event_date:
            # one event keeps one pending night line, rewritten from current state, not one row per poll
            event = self.store.get_event(alert["symbol"], event_date)
            pending = self.store.alert(event["pending_alert_id"]) if event and event.get("pending_alert_id") else None
            if pending and pending["deferred"] and pending["digested_at"] is None:
                self.store.update_alert(pending["id"], text=alert["text"], digest_text=alert.get("digest_text"))
                return pending["id"]
        alert_id = self.store.add_alert(alert["symbol"], alert.get("kind", ""), alert["text"],
                                        bool(alert.get("escalate")) or ring, now, deferred=hold,
                                        event_date=event_date, digest_text=alert.get("digest_text"))
        if hold:
            return alert_id
        if alert.get("price_move"):
            self._supersede(snap, alert_id, alert.get("symbols") or [alert["symbol"]])
        self._send_telegram(snap, alert_id, alert["text"], now)
        if (night and ring) or alert.get("earnings_unacked"):
            self._escalate(snap, alert_id, now)
        return alert_id

    def deferred(self, alert_id: int) -> bool:
        row = self.store.alert(alert_id)
        return bool(row and row["deferred"])

    def _supersede(self, snap: dict, new_id: int, symbols: list[str]) -> None:
        """A new push on a symbol closes that symbol's earlier live alert and stops its ringing (one ring per symbol)."""
        marks = ",".join("?" for _ in symbols)
        pushover = snap.get("pushover") or {}
        for row in self.store.alerts_where(
                f"symbol IN ({marks}) AND kind IN {PRICE_KINDS} AND id != ? AND acked_at IS NULL"
                " AND superseded_by IS NULL AND deferred = 0", (*symbols, new_id)):
            self.store.update_alert(row["id"], superseded_by=new_id)
            if row["receipt"] and not row["receipt_closed"]:
                self.channels.cancel_receipt(pushover, row["receipt"])
                self.store.update_alert(row["id"], receipt_closed=1)

    def _send_telegram(self, snap: dict, alert_id: int, text: str, now: float) -> None:
        config = snap.get("telegram") or {}
        message_id = self.channels.telegram_alert(config, text, alert_id)
        fields = {"last_sent_at": now}
        if message_id is not None:
            fields |= {"tg_message_id": message_id, "tg_chat_id": config.get("chat_id")}
        self.store.update_alert(alert_id, **fields)

    def _escalate(self, snap: dict, alert_id: int, now: float) -> None:
        config = snap.get("pushover") or {}
        if not (config.get("user_key") and config.get("app_token")):
            return
        row = self.store.alert(alert_id)
        receipt = self.channels.pushover_emergency(config, row["text"])
        if receipt:
            self.store.update_alert(alert_id, receipt=receipt, escalated_at=now)

    # --- the periodic pass -------------------------------------------------------------------------
    def tick(self, snap: dict) -> None:
        now = self.clock()
        self._digest(snap, now)
        pushover = snap.get("pushover") or {}
        has_pushover = bool(pushover.get("user_key") and pushover.get("app_token"))
        # a message Telegram never accepted (the send failed) is retried from its row, not re-decided
        for row in self.store.alerts_where(
                "acked_at IS NULL AND superseded_by IS NULL AND deferred = 0 AND tg_message_id IS NULL"
                " AND last_sent_at IS NOT NULL AND created_at >= ?", (now - RETRY_WINDOW,)):
            if now - row["last_sent_at"] >= RETRY_EVERY:
                self._send_telegram(snap, row["id"], row["text"], now)
        for row in self.store.alerts_where(
                "acked_at IS NULL AND superseded_by IS NULL AND escalate = 1 AND deferred = 0 AND last_sent_at IS NOT NULL"):
            if row["receipt"]:
                continue                                    # already ringing; the poll below watches it
            if has_pushover:
                if row["escalated_at"] is None and now - row["created_at"] >= ESCALATE_AFTER:
                    self._escalate(snap, row["id"], now)
            elif row["resends"] < MAX_RESENDS and now - row["last_sent_at"] >= RESEND_EVERY:
                # only the latest alert of an event resends, and it says when it went out
                stamp = datetime.fromtimestamp(row["created_at"], BEIJING).strftime("%H:%M")
                self._send_telegram(snap, row["id"], f"（{stamp} 发出，价格可能已变）\n{row['text']}", now)
                self.store.update_alert(row["id"], resends=row["resends"] + 1)
        self._sync_receipts(pushover)

    def _sync_receipts(self, pushover: dict) -> None:
        for row in self.store.alerts_where("receipt IS NOT NULL AND receipt_closed = 0"):
            if row["acked_at"] is not None:                 # acknowledged on Telegram: stop the ringing
                self.channels.cancel_receipt(pushover, row["receipt"])
                self.store.update_alert(row["id"], receipt_closed=1)
                continue
            status = self.channels.receipt_status(pushover, row["receipt"])
            if status.get("acknowledged"):
                self.store.ack_alert(row["id"], self.clock())
                self.store.update_alert(row["id"], receipt_closed=1)
            elif status.get("expired"):
                self.store.update_alert(row["id"], receipt_closed=1)

    def _digest(self, snap: dict, now: float) -> None:
        if is_night(now):
            return
        rows = self.store.alerts_where("deferred = 1 AND digested_at IS NULL")
        if not rows:
            return
        body = "【夜间汇总】昨夜到现在没有直接打扰你的提醒：\n" + "\n".join(f"· {r.get('digest_text') or r['text'].splitlines()[0]}" for r in rows)
        if self.channels.telegram_text(snap.get("telegram") or {}, body):
            for row in rows:
                self.store.update_alert(row["id"], digested_at=now)
                if row.get("event_date") and row["kind"] in ("short", "daily", "gap", "update"):
                    self.store.rebase_event(row["symbol"], row["event_date"], now)   # the owner has now seen that price
