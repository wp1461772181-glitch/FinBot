"""The channel-neutral outbox (stage 1e).

A proactive message (an alert, a brief, an earnings notice, a bot's own notify) is queued by
``agent_telegram.enqueue`` into ``agent_telegram_messages``; each row carries a channel.  The owner's stored
preference (``agent_channel_prefs``) decides which channel(s) a new message gets rows on; a row that fails three
times or sits unsent too long is closed and re-queued on the next listed channel; the bridges record what they
sent and what the owner answered.  With no preference stored a message is one Telegram row, as before.

Only the owner is ever messaged: Telegram goes to the bound chat, WeChat to the login's own owner id (which stays
in the bridge's state file; this module reads only whether it is there).  Nothing here stores or returns a token.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from .agent_chat_models import AgentBot, AgentChannelPref, AgentTelegramMessage
from .database import SessionLocal

CHANNELS = ("telegram", "wechat")
MODES = ("first", "all")
STUCK_SECONDS = 300
FAILURES = ("send_failed", "expired", "not_connected")
DEFAULT_PREFS = {"channels": ["telegram"], "mode": "first"}
DELIVERY_TEXT_CHARS = 120


def prefs(db, owner_hash: str) -> dict:
    """The owner's channels in order and the mode; Telegram only when nothing (usable) is stored."""
    row = db.get(AgentChannelPref, owner_hash)
    if row is None:
        return {"channels": list(DEFAULT_PREFS["channels"]), "mode": DEFAULT_PREFS["mode"]}
    try:
        listed = json.loads(row.channels)
    except ValueError:
        listed = []
    wanted = [c for c in dict.fromkeys(listed if isinstance(listed, list) else []) if c in CHANNELS]
    if not wanted:
        return {"channels": list(DEFAULT_PREFS["channels"]), "mode": DEFAULT_PREFS["mode"]}
    return {"channels": wanted, "mode": row.mode if row.mode in MODES else DEFAULT_PREFS["mode"]}


def set_prefs(owner_hash: str, channels: list[str], mode: str) -> dict:
    if (not isinstance(channels, (list, tuple)) or not channels or any(c not in CHANNELS for c in channels)
            or len(set(channels)) != len(channels) or mode not in MODES):
        raise ValueError("invalid_channels")
    stored = json.dumps(list(channels))
    with SessionLocal() as db:
        row = db.get(AgentChannelPref, owner_hash)
        if row is None:
            db.add(AgentChannelPref(owner_hash=owner_hash, channels=stored, mode=mode, updated_at=datetime.now(UTC)))
        else:
            row.channels, row.mode, row.updated_at = stored, mode, datetime.now(UTC)
        db.commit()
    return {"channels": list(channels), "mode": mode}


def available(db, owner_hash: str, channel: str, bot) -> bool:
    """Whether the channel can take a message now.  Telegram: the bot's own bound Telegram bot or the shared
    bind (today's rule).  WeChat: the bridge has a login saved (only the presence of its two fields is read)."""
    if channel == "telegram":
        from . import agent_telegram
        return (bot is not None and agent_telegram.own_channel(db, owner_hash, bot.id) is not None) or agent_telegram._bound(db, owner_hash)
    if channel == "wechat":
        from . import agent_wechat
        state = agent_wechat.load_state()
        return bool(state.get("bot_token")) and bool(state.get("owner_user_id"))
    return False


def targets(db, owner_hash: str, bot, override: list[str] | None = None) -> list[str]:
    """The channels a new message gets rows on.  Mode ``all``: every available channel in order; ``first``: the
    first available one.  ``override`` (a producer that knows better, such as the WeChat stale-login notice) names
    the channels instead of the preference: each one of them that is available."""
    if override is not None:
        wanted, mode = [c for c in dict.fromkeys(override) if c in CHANNELS], "all"
    else:
        stored = prefs(db, owner_hash)
        wanted, mode = stored["channels"], stored["mode"]
    usable = [c for c in wanted if available(db, owner_hash, c, bot)]
    return usable if mode == "all" else usable[:1]


def shape(db, owner_hash: str, bot, channel: str, text: str) -> tuple[str, uuid.UUID | None]:
    """A row's text and Telegram bot for one channel.  ``text`` carries 「【名字】」 in front when it has one.  A bot's
    own Telegram bot sends without the name; the shared bot and WeChat (one bot for all) keep it."""
    if channel == "telegram" and bot is not None:
        from . import agent_telegram
        own = agent_telegram.own_channel(db, owner_hash, bot.id)
        if own is not None:
            return text.removeprefix(f"【{bot.name}】\n"), own.id
    return text, None


def pending(owner_hash: str, channel: str, limit: int = 20, telegram_bot_row_id=None) -> list[dict]:
    """Queued messages of one channel, oldest first.  Telegram: the shared bot's (None) or a bot's own."""
    with SessionLocal() as db:
        query = select(AgentTelegramMessage).where(AgentTelegramMessage.owner_hash == owner_hash,
                                                   AgentTelegramMessage.status == "pending",
                                                   AgentTelegramMessage.channel == channel)
        if channel == "telegram":
            query = query.where(AgentTelegramMessage.telegram_bot_row_id.is_(None) if telegram_bot_row_id is None
                                else AgentTelegramMessage.telegram_bot_row_id == uuid.UUID(str(telegram_bot_row_id)))
        rows = db.scalars(query.order_by(AgentTelegramMessage.created_at).limit(limit)).all()
        return [{"id": str(r.id), "bot_id": str(r.bot_id) if r.bot_id else None, "text": r.text} for r in rows]


def _locked(db, message_id):
    return db.scalars(select(AgentTelegramMessage).where(AgentTelegramMessage.id == uuid.UUID(str(message_id)))
                      .with_for_update()).first()


def mark_sent(message_id, external_id: int | None = None) -> None:
    """The channel took the message.  A row the sweep closed as expired a moment before the send finished is
    still recorded as sent (it was); a row closed for failed sends stays closed."""
    with SessionLocal() as db:
        row = _locked(db, message_id)
        if row is not None and (row.status == "pending" or (row.status == "failed" and row.failure == "expired")):
            row.status, row.failure, row.sent_at, row.telegram_message_id = "sent", None, datetime.now(UTC), external_id
            db.commit()


def _close(db, row, code: str) -> None:
    row.status, row.failure = "failed", code if code in FAILURES else "send_failed"
    fail_over(db, row)


def mark_failed(message_id, code: str = "send_failed") -> None:
    """One more failed attempt; at ``SEND_ATTEMPTS`` the row is closed and re-queued on the next channel."""
    from .agent_telegram import SEND_ATTEMPTS
    with SessionLocal() as db:
        row = _locked(db, message_id)
        if row is None or row.status != "pending":
            return
        row.attempts += 1
        if row.attempts >= SEND_ATTEMPTS:
            _close(db, row, code)
        db.commit()


def fail_over(db, row) -> bool:
    """Queue the message of a closed row on the next channel of the owner's preference that is available and has
    no row in the message's group.  The caller holds the row (locked) and commits."""
    wanted = prefs(db, row.owner_hash)["channels"]
    bot = db.get(AgentBot, row.bot_id) if row.bot_id else None
    have = {row.channel}
    if row.group_id is not None:
        have |= set(db.scalars(select(AgentTelegramMessage.channel).where(AgentTelegramMessage.group_id == row.group_id)))
    text = row.text
    if row.telegram_bot_row_id is not None and bot is not None and not text.startswith(f"【{bot.name}】"):
        text = f"【{bot.name}】\n{text}"      # it went out of the bot's own Telegram bot, with no name in front
    for channel in wanted:
        if channel in have or not available(db, row.owner_hash, channel, bot):
            continue
        if row.group_id is None:
            row.group_id = uuid.uuid4()
        shaped, own_id = shape(db, row.owner_hash, bot, channel, text)
        db.add(AgentTelegramMessage(owner_hash=row.owner_hash, bot_id=row.bot_id, source=row.source, text=shaped,
                                    status="pending", channel=channel, group_id=row.group_id, created_at=datetime.now(UTC),
                                    inbox_item_id=row.inbox_item_id, telegram_bot_row_id=own_id))
        db.flush()
        return True
    return False


def expire_stuck(owner_hash: str, now: datetime | None = None) -> int:
    """Close every pending row of this owner older than ``STUCK_SECONDS`` (its bridge is not taking it) and re-queue
    each on the next channel.  Rows are locked with SKIP LOCKED, so two bridges and the API calling at once never
    close or fail over the same row twice."""
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=STUCK_SECONDS)
    with SessionLocal() as db:
        rows = db.scalars(select(AgentTelegramMessage).where(
            AgentTelegramMessage.owner_hash == owner_hash, AgentTelegramMessage.status == "pending",
            AgentTelegramMessage.created_at < cutoff).order_by(AgentTelegramMessage.created_at)
            .with_for_update(skip_locked=True)).all()
        for row in rows:
            _close(db, row, "expired")
        db.commit()
        return len(rows)


def acknowledge(owner_hash: str, channel: str, now: datetime | None = None) -> int:
    """The owner wrote on this channel: its sent, not yet acknowledged rows are marked."""
    with SessionLocal() as db:
        result = db.execute(update(AgentTelegramMessage).where(
            AgentTelegramMessage.owner_hash == owner_hash, AgentTelegramMessage.channel == channel,
            AgentTelegramMessage.status == "sent", AgentTelegramMessage.acked_at.is_(None))
            .values(acked_at=now or datetime.now(UTC)))
        db.commit()
        return int(result.rowcount or 0)


def deliveries(owner_hash: str, limit: int = 50) -> list[dict]:
    """Proactive messages, newest first.  Replies the bridge sent are not messages of this list."""
    with SessionLocal() as db:
        rows = db.scalars(select(AgentTelegramMessage).where(
            AgentTelegramMessage.owner_hash == owner_hash, AgentTelegramMessage.source != "reply")
            .order_by(AgentTelegramMessage.created_at.desc(), AgentTelegramMessage.id).limit(max(1, int(limit)))).all()

        def stamp(value):
            return value.isoformat() if value is not None else None
        return [{"id": str(r.id), "group_id": str(r.group_id) if r.group_id else None,
                 "bot_id": str(r.bot_id) if r.bot_id else None, "source": r.source, "channel": r.channel,
                 "status": r.status, "failure": r.failure, "created_at": stamp(r.created_at), "sent_at": stamp(r.sent_at),
                 "acked_at": stamp(r.acked_at), "text": r.text[:DELIVERY_TEXT_CHARS]} for r in rows]
