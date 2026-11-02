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
