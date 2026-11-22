"""WeChat channel (ClawBot, the iLink bot API) for the personal agent: protocol client, state file, text helpers.

The protocol is read from Tencent's MIT-licensed @tencent-weixin/openclaw-weixin 2.4.10 and was checked against the
real service on the box (2026-11-22): one long-polled ``getupdates``, one ``sendmessage`` per text, and a
``context_token`` that arrives with every inbound message and is echoed back in the reply.  Whether a message sent
long after the user's last one still arrives is not settled; nothing here relies on it.

The state file (bot token, polling cursor, the owner's WeChat id, context tokens) is a credential: it is written
0600 under data/ and never printed or logged.  Only messages from the one WeChat id that scanned the login are
answered; anyone else is ignored.
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
import time
import uuid
from pathlib import Path

ILINK_BASE = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.4.10"
CLIENT_VERSION = "132106"  # 0x00MMNNPP of the plugin version above, as the official plugin computes it
BASE_INFO = {"channel_version": CHANNEL_VERSION, "bot_agent": "FinBot/1.0"}
STALE_ERRCODE = -14  # the session is no longer valid: the official plugin pauses an hour, then asks for a new scan
USER, BOT = 1, 2  # message_type
TEXT_ITEM = 1
MESSAGE_CHARS = 1800  # one WeChat text; the service documents no limit, so stay well under what a phone shows at once

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def state_path() -> Path:
    return Path(os.environ.get("WECHAT_STATE_PATH") or _PROJECT_ROOT / "data" / "wechat-bridge.json")


def load_state(path: Path | None = None) -> dict:
    try:
        state = json.loads((path or state_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state: dict, path: Path | None = None) -> None:
    """Atomic, owner-only: the file holds the bot token."""
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False)
    os.replace(tmp, path)


def new_state(*, bot_token: str, baseurl: str, bot_id: str, owner_user_id: str, cursor: str = "", context_tokens=None) -> dict:
    return {"bot_token": bot_token, "baseurl": baseurl or ILINK_BASE, "ilink_bot_id": bot_id,
            "owner_user_id": owner_user_id, "get_updates_buf": cursor, "context_tokens": dict(context_tokens or {})}


def ilink_headers(token: str | None = None, *, post: bool = True) -> dict:
    headers = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": CLIENT_VERSION}
    if post:
        headers.update({"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
                        "X-WECHAT-UIN": base64.b64encode(str(random.getrandbits(32)).encode()).decode()})
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def poll_status(response: dict) -> str:
    """'stale' (the login no longer works), 'rejected' (the service refused this poll) or 'ok'."""
    codes = (response.get("errcode"), response.get("ret"))
    if STALE_ERRCODE in codes:
        return "stale"
    return "rejected" if any(code not in (None, 0) for code in codes) else "ok"


def send_result(response: dict) -> str | None:
    """None when the service accepted the message, else the short reason it gave."""
    if poll_status(response) == "ok":
        return None
    return str(response.get("errmsg") or response.get("errcode") or response.get("ret") or "rejected")[:120]


def inbound_text(message: dict) -> str:
    items = message.get("item_list") or []
    return "\n".join(str((item.get("text_item") or {}).get("text") or "") for item in items
                     if isinstance(item, dict) and item.get("type") == TEXT_ITEM).strip()


def from_owner(message: dict, state: dict) -> bool:
    owner = state.get("owner_user_id")
    return bool(owner) and message.get("message_type") == USER and message.get("from_user_id") == owner


_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)


def plain_text(text: str) -> str:
    """WeChat shows text as typed: drop the markdown marks that would show as stray symbols."""
    text = _HEADING.sub("", text)
    text = _BOLD.sub(r"\2", text)
    return text.replace("`", "").strip()


def split_text(text: str, limit: int = MESSAGE_CHARS) -> list[str]:
    from .agent_telegram import split_for_telegram
    return split_for_telegram(text, limit)


class Ilink:
    """The three calls the bridge needs, over an httpx-style async client."""

    def __init__(self, http, state: dict):
        self.http, self.state = http, state

    async def _post(self, path: str, body: dict, timeout: float) -> dict:
        url = f"{str(self.state.get('baseurl') or ILINK_BASE).rstrip('/')}/ilink/bot/{path}"
        response = await self.http.post(url, json={**body, "base_info": BASE_INFO},
                                        headers=ilink_headers(self.state.get("bot_token")), timeout=timeout)
        response.raise_for_status()
        return response.json() if response.content.strip() else {}

    async def get_updates(self) -> dict:
        return await self._post("getupdates", {"get_updates_buf": self.state.get("get_updates_buf", "")}, 45)

    async def send_text(self, to_user: str, text: str, context_token: str | None = None) -> dict:
        message = {"from_user_id": "", "to_user_id": to_user, "client_id": uuid.uuid4().hex, "message_type": BOT,
                   "message_state": 2, "item_list": [{"type": TEXT_ITEM, "text_item": {"text": text}}]}
        if context_token:
            message["context_token"] = context_token
        return await self._post("sendmessage", {"msg": message}, 15)


async def login(http, on_qr, *, timeout: float = 480, sleep=None) -> dict | None:
    """Ask for a QR code, hand its link to ``on_qr``, wait for the scan.  Returns the new state, or None when the
    code expired three times or was never scanned.  The scanning WeChat id becomes the owner."""
    import asyncio
    sleep = sleep or asyncio.sleep

    async def new_code():
        response = await http.post(f"{ILINK_BASE}/ilink/bot/get_bot_qrcode", params={"bot_type": 3},
                                   json={"local_token_list": []}, headers=ilink_headers(), timeout=15)
        response.raise_for_status()
        data = response.json()
        on_qr(str(data.get("qrcode_img_content") or ""))
        return str(data.get("qrcode") or "")

    code, host, refreshes, deadline = await new_code(), ILINK_BASE, 0, time.time() + timeout
    while time.time() < deadline:
        try:
            response = await http.get(f"{host}/ilink/bot/get_qrcode_status", params={"qrcode": code},
                                      headers=ilink_headers(post=False), timeout=40)
            data = response.json()
        except Exception:  # noqa: BLE001 - a dropped poll is retried until the deadline
            await sleep(2)
            continue
        status = data.get("status")
        if status == "confirmed" and data.get("bot_token"):
            return new_state(bot_token=data["bot_token"], baseurl=data.get("baseurl") or host,
                             bot_id=str(data.get("ilink_bot_id") or ""), owner_user_id=str(data.get("ilink_user_id") or ""))
        if status == "scaned_but_redirect" and data.get("redirect_host"):
            host = "https://" + str(data["redirect_host"])
        elif status in ("expired", "verify_code_blocked"):
            refreshes += 1
            if refreshes > 3:
                return None
            code, host = await new_code(), ILINK_BASE
        elif status == "binded_redirect":
            return None
        await sleep(1)
    return None
