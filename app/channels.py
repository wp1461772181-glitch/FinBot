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
SENTINEL_COPY_STALE = timedelta(minutes=30)     # a WeChat copy of a price alert older than this is not sent any more
CLAIM_SECONDS = 180      # a bridge that took a row this recently is still sending it: the sweep leaves it
ACK_DAYS = 7             # an acknowledgement reaches back this far, not into older history
FAILURES = ("send_failed", "expired", "partial")
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


def check_prefs(channels: list[str], mode: str) -> None:
    """What a preference may be (one or more known channels, none twice, a known mode); ValueError(invalid_channels) otherwise."""
    if (not isinstance(channels, (list, tuple)) or not channels or any(c not in CHANNELS for c in channels)
            or len(set(channels)) != len(channels) or mode not in MODES):
        raise ValueError("invalid_channels")


def set_prefs(owner_hash: str, channels: list[str], mode: str) -> dict:
    check_prefs(channels, mode)
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
        # ``stale_since`` is written by the bridge while the login needs a new scan, and cleared by its next good poll.
        return bool(state.get("bot_token")) and bool(state.get("owner_user_id")) and not state.get("stale_since")
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


def pending(owner_hash: str, channel: str, limit: int = 20, telegram_bot_row_id=None,
            now: datetime | None = None) -> list[dict]:
    """Queued messages of one channel, oldest first.  Telegram: the shared bot's (None) or a bot's own.  The rows
    returned are claimed (``claimed_at``): the sweep leaves them alone for ``CLAIM_SECONDS``, so a row a bridge is
    sending is not closed and failed over under it.  A bridge that died stops claiming and its rows expire.  Each item carries its
    ``source`` and ``group_id`` (the Telegram bridge puts 「有用／没用」 on a duty or brief message by its group)."""
    with SessionLocal() as db:
        query = select(AgentTelegramMessage).where(AgentTelegramMessage.owner_hash == owner_hash,
                                                   AgentTelegramMessage.status == "pending",
                                                   AgentTelegramMessage.channel == channel)
        if channel == "telegram":
            query = query.where(AgentTelegramMessage.telegram_bot_row_id.is_(None) if telegram_bot_row_id is None
                                else AgentTelegramMessage.telegram_bot_row_id == uuid.UUID(str(telegram_bot_row_id)))
        rows = db.scalars(query.order_by(AgentTelegramMessage.created_at).limit(limit).with_for_update()).all()
        stamp = now or datetime.now(UTC)
        for row in rows:
            row.claimed_at = stamp
        db.commit()
        return [{"id": str(r.id), "bot_id": str(r.bot_id) if r.bot_id else None, "text": r.text, "source": r.source,
                 "group_id": str(r.group_id) if r.group_id else None} for r in rows]


def _locked(db, message_id):
    return db.scalars(select(AgentTelegramMessage).where(AgentTelegramMessage.id == uuid.UUID(str(message_id)))
                      .with_for_update()).first()


def mark_sent(message_id, external_id: int | None = None) -> None:
    """The channel took the message.  A closed row stays closed: the claim lease keeps the sweep off a row a bridge
    is sending, so a closed row was not being sent."""
    with SessionLocal() as db:
        row = _locked(db, message_id)
        if row is not None and row.status == "pending":
            row.status, row.failure, row.sent_at, row.telegram_message_id = "sent", None, datetime.now(UTC), external_id
            db.commit()


def claim(message_id, now: datetime | None = None) -> None:
    """Re-stamp the lease of one pending row; a bridge calls it just before it starts sending that row."""
    with SessionLocal() as db:
        row = _locked(db, message_id)
        if row is not None and row.status == "pending":
            row.claimed_at = now or datetime.now(UTC)
            db.commit()


def mark_partial(message_id) -> None:
    """Only the first part of a long message reached the channel: the row counts as sent (sending it again would
    show the owner the same words twice there), says so (``failure="partial"``), and the full text goes to the
    next channel the preference lists, if one is available and has no row in the message's group."""
    with SessionLocal() as db:
        row = _locked(db, message_id)
        if row is not None and row.status == "pending":
            row.status, row.failure, row.sent_at = "sent", "partial", datetime.now(UTC)
            fail_over(db, row)
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
    if row.source == "sentinel":
        return False        # the WeChat copy of an alert the sentinel already sent to Telegram: a fail-over would be a second copy there
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


def _delivered_elsewhere(db, row) -> bool:
    if row.group_id is None:
        return False
    return db.scalar(select(AgentTelegramMessage.id).where(
        AgentTelegramMessage.group_id == row.group_id, AgentTelegramMessage.id != row.id,
        AgentTelegramMessage.status == "sent", AgentTelegramMessage.failure.is_(None)).limit(1)) is not None


def expire_stuck(owner_hash: str, now: datetime | None = None) -> int:
    """Close every pending row of this owner older than ``STUCK_SECONDS`` that no bridge claimed in the last
    ``CLAIM_SECONDS``: when it is re-queued on another channel, or when its message already reached the owner on
    another channel (a sibling row of its group is ``sent``, whole), so a bridge coming back hours later does not
    send a duplicate.  A row with neither stays pending (its bridge sends it when it returns, or the next sweep
    finds a channel).  Returns how many were closed.
    Rows are locked with SKIP LOCKED, so two bridges and the API calling at once never close or fail over the
    same row twice."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=STUCK_SECONDS)
    lease = now - timedelta(seconds=CLAIM_SECONDS)
    with SessionLocal() as db:
        rows = db.scalars(select(AgentTelegramMessage).where(
            AgentTelegramMessage.owner_hash == owner_hash, AgentTelegramMessage.status == "pending",
            AgentTelegramMessage.created_at < cutoff,
            (AgentTelegramMessage.claimed_at.is_(None)) | (AgentTelegramMessage.claimed_at <= lease)).order_by(AgentTelegramMessage.created_at)
            .with_for_update(skip_locked=True)).all()
        closed = 0
        stale = now - SENTINEL_COPY_STALE
        for row in rows:
            # the WeChat copy of an alert never fails over (Telegram has the alert from the sentinel itself); once it is this old a
            # price it quotes is stale, so it is closed rather than sent when the bridge comes back hours later
            if (row.source == "sentinel" and row.created_at < stale) or _delivered_elsewhere(db, row) or fail_over(db, row):
                row.status, row.failure = "failed", "expired"
                closed += 1
        db.commit()
        return closed


def acknowledge(owner_hash: str, channel: str, now: datetime | None = None, seen_at: datetime | None = None) -> int:
    """The owner wrote on this channel: its proactive rows sent in the last ``ACK_DAYS`` days and not yet
    acknowledged are marked.  Replies and older history are left alone.  ``seen_at`` is when the owner's message
    was written: only rows sent by then are marked (a backlog a restarted bridge sent after it is not), and it
    is the time recorded."""
    now = seen_at or now or datetime.now(UTC)
    with SessionLocal() as db:
        result = db.execute(update(AgentTelegramMessage).where(
            AgentTelegramMessage.owner_hash == owner_hash, AgentTelegramMessage.channel == channel,
            AgentTelegramMessage.status == "sent", AgentTelegramMessage.acked_at.is_(None),
            AgentTelegramMessage.source != "reply",
            AgentTelegramMessage.sent_at >= now - timedelta(days=ACK_DAYS),
            *([AgentTelegramMessage.sent_at <= seen_at] if seen_at is not None else []))
            .values(acked_at=now))
        db.commit()
        return int(result.rowcount or 0)


def deliveries(owner_hash: str, limit: int = 50, before: tuple | None = None) -> list[dict]:
    """Proactive messages, newest first.  Replies the bridge sent are not messages of this list.
    ``before`` is the ``(created_at, id)`` of the last row of the page already seen: the list goes on after it."""
    with SessionLocal() as db:
        query = select(AgentTelegramMessage).where(
            AgentTelegramMessage.owner_hash == owner_hash, AgentTelegramMessage.source != "reply")
        if before is not None:       # the order is created_at descending, then id ascending
            seen_at, seen_id = before
            query = query.where((AgentTelegramMessage.created_at < seen_at) | (
                (AgentTelegramMessage.created_at == seen_at) & (AgentTelegramMessage.id > seen_id)))
        rows = db.scalars(query.order_by(AgentTelegramMessage.created_at.desc(), AgentTelegramMessage.id)
                          .limit(max(1, int(limit)))).all()

        def stamp(value):
            return value.isoformat() if value is not None else None
        return [{"id": str(r.id), "group_id": str(r.group_id) if r.group_id else None,
                 "bot_id": str(r.bot_id) if r.bot_id else None, "source": r.source, "channel": r.channel,
                 "status": r.status, "failure": r.failure, "created_at": stamp(r.created_at), "sent_at": stamp(r.sent_at),
                 "acked_at": stamp(r.acked_at), "text": r.text[:DELIVERY_TEXT_CHARS]} for r in rows]
