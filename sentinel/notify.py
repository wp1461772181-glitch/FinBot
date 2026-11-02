"""Direct notifications (Telegram, optional Pushover), stdlib only."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger("sentinel.notify")


def _post_form(url: str, fields: dict, timeout: float = 15) -> bool:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # honours the proxy env: the VM egress needs it
        return 200 <= resp.status < 300


def send_telegram(config: dict, text: str) -> bool:
    token, chat_id = config.get("bot_token"), config.get("chat_id")
    if not token or not chat_id:
        return False
    try:
        return _post_form(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat_id, "text": text})
    except Exception as exc:  # never include the URL: it holds the token
        logger.warning("telegram send failed: %s", type(exc).__name__)
        return False


def send_pushover(config: dict, text: str) -> bool:
    user, token = config.get("user_key"), config.get("app_token")
    if not user or not token:
        return False
    try:
        return _post_form("https://api.pushover.net/1/messages.json", {"user": user, "token": token, "message": text})
    except Exception as exc:
        logger.warning("pushover send failed: %s", type(exc).__name__)
        return False


def notify(snapshot: dict, text: str) -> bool:
    """Telegram first, Pushover as the fallback; False if nothing was delivered."""
    if send_telegram(snapshot.get("telegram") or {}, text):
        return True
    if send_pushover(snapshot.get("pushover") or {}, text):
        return True
    logger.error("no notification channel delivered: %s", text)
    return False


# --- alert channels for the escalation (Task 12) ---------------------------------------------------------
PUSHOVER_API = "https://api.pushover.net/1"


def _post_json(url: str, fields: dict, timeout: float = 15) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


def _get_json(url: str, timeout: float = 15) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


class Channels:
    """The real channels behind the escalation; tests pass a fake with the same methods."""

    def telegram_alert(self, config: dict, text: str, alert_id: int) -> int | None:
        """An alert with the 「收到」button; returns the Telegram message id (replies to it count as acks)."""
        token, chat_id = config.get("bot_token"), config.get("chat_id")
        if not token or not chat_id:
            return None
        keyboard = {"inline_keyboard": [[{"text": "收到", "callback_data": f"ack:{alert_id}"}]]}
        try:
            body = _post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                              {"chat_id": chat_id, "text": text, "reply_markup": json.dumps(keyboard)})
            return int((body.get("result") or {}).get("message_id"))
        except Exception as exc:  # never include the URL: it holds the token
            logger.warning("telegram alert failed: %s", type(exc).__name__)
            return None

    def telegram_text(self, config: dict, text: str) -> bool:
        return send_telegram(config, text)

    def pushover_emergency(self, config: dict, text: str) -> str | None:
        """priority 2: rings every 60 s until acknowledged, stops by itself after 30 minutes."""
        user, token = config.get("user_key"), config.get("app_token")
        if not user or not token:
            return None
        try:
            body = _post_json(f"{PUSHOVER_API}/messages.json", {"user": user, "token": token, "message": text,
                                                                "priority": 2, "retry": 60, "expire": 1800})
            return str(body["receipt"]) if body.get("status") == 1 and body.get("receipt") else None
        except Exception as exc:
            logger.warning("pushover emergency failed: %s", type(exc).__name__)
            return None

    def receipt_status(self, config: dict, receipt: str) -> dict:
        try:
            query = urllib.parse.urlencode({"token": config.get("app_token", "")})
            body = _get_json(f"{PUSHOVER_API}/receipts/{receipt}.json?{query}")
            return {"acknowledged": bool(body.get("acknowledged")), "expired": bool(body.get("expired"))}
        except Exception as exc:
            logger.warning("pushover receipt poll failed: %s", type(exc).__name__)
            return {"acknowledged": False, "expired": False, "error": True}

    def cancel_receipt(self, config: dict, receipt: str) -> None:
        try:
            _post_json(f"{PUSHOVER_API}/receipts/{receipt}/cancel.json", {"token": config.get("app_token", "")})
        except Exception as exc:
            logger.warning("pushover cancel failed: %s", type(exc).__name__)
