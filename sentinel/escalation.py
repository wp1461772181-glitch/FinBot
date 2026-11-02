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


def is_night(ts: float) -> bool:
    return datetime.fromtimestamp(ts, BEIJING).hour < NIGHT_END_HOUR


def rings_at_night(alert: dict) -> bool:
    if alert.get("kind") == "earnings_followup":
        return alert.get("bias") == "down" and alert.get("confidence") == "high"
    return bool(alert.get("escalate") and alert.get("held") and (alert.get("weight_pct") or 0) >= NIGHT_WEIGHT_PCT)


class Escalator:
    def __init__(self, store: Store, channels, clock: Callable[[], float] = time.time) -> None:
        self.store, self.channels, self.clock = store, channels, clock

    # --- a new alert ------------------------------------------------------------------------------
    def raise_alert(self, snap: dict, alert: dict) -> int:
        now = self.clock()
        night = is_night(now)
        ring = rings_at_night(alert)
        hold = night and not ring
        alert_id = self.store.add_alert(alert["symbol"], alert.get("kind", ""), alert["text"],
                                        bool(alert.get("escalate")) or ring, now, deferred=hold)
        if hold:
            return alert_id
        self._send_telegram(snap, alert_id, alert["text"], now)
        if (night and ring) or alert.get("earnings_unacked"):
            self._escalate(snap, alert_id, now)
        return alert_id

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
        for row in self.store.alerts_where("acked_at IS NULL AND escalate = 1 AND deferred = 0 AND last_sent_at IS NOT NULL"):
            if row["receipt"]:
                continue                                    # already ringing; the poll below watches it
            if has_pushover:
                if row["escalated_at"] is None and now - row["created_at"] >= ESCALATE_AFTER:
                    self._escalate(snap, row["id"], now)
            elif row["resends"] < MAX_RESENDS and now - row["last_sent_at"] >= RESEND_EVERY:
                self._send_telegram(snap, row["id"], row["text"], now)
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
        body = "【夜间汇总】昨夜到现在没有直接打扰你的提醒：\n" + "\n".join(f"· {r['text'].splitlines()[0]}" for r in rows)
        if self.channels.telegram_text(snap.get("telegram") or {}, body):
            for row in rows:
                self.store.update_alert(row["id"], digested_at=now)
