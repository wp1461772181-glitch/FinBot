"""Stage 1e, task 1: the channel-neutral outbox (app/channels.py).

A queued message carries a channel; the owner's stored preference decides which channel(s) a new message goes to;
a failed or stuck row is re-queued on the next channel; acknowledgement is recorded.  With no preference stored
everything is exactly as before (one Telegram row)."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app import agent_bots as bots
from app import agent_telegram as tg
from app import agent_wechat
from app import channels
from app.agent_chat_models import AgentChannelPref, AgentTelegramBind, AgentTelegramMessage
from app.database import SessionLocal
from tests.test_agent_notify import CHAT, NOW, OWNER, OWNER_HASH, OTHER_HASH, owner, _bind  # noqa: F401  (fixture)

H = {"X-Chat-Session": OWNER}
GUEST = {"X-Chat-Session": "g" * 40}
LOGIN = {"bot_token": "wx-token-not-a-secret", "owner_user_id": "wx-owner"}


@pytest.fixture
def chan(owner, monkeypatch):
    with SessionLocal() as db:
        db.query(AgentChannelPref).delete()
        db.commit()
    state = {}
    monkeypatch.setattr(agent_wechat, "load_state", lambda path=None: dict(state))
    return state  # a test connects WeChat with state.update(LOGIN)


def _bot():
    return bots.ensure_default_bot(OWNER_HASH)


def _queue(text="有新消息", *, source="notify", now=NOW):
    bot = _bot()
    with SessionLocal() as db:
        left = tg.enqueue(db, OWNER_HASH, bot.id, text, source=source, now=now)
        db.commit()
    return left


def _rows(**where):
    with SessionLocal() as db:
        rows = db.query(AgentTelegramMessage).filter_by(**where).order_by(AgentTelegramMessage.created_at,
                                                                         AgentTelegramMessage.channel).all()
        for row in rows:
            db.expunge(row)
        return rows


def _plant(channel="telegram", *, status="pending", created=NOW, group=None, source="notify", text="m", attempts=0,
           failure=None, claimed=None, sent=None):
    with SessionLocal() as db:
        row = AgentTelegramMessage(owner_hash=OWNER_HASH, bot_id=_bot().id, source=source, text=text, status=status,
                                   channel=channel, group_id=group, created_at=created, attempts=attempts,
                                   failure=failure, claimed_at=claimed, sent_at=sent)
        db.add(row)
        db.commit()
        return str(row.id)


# --- preferences -------------------------------------------------------------------------------------

def test_default_prefs_are_telegram_only(chan):
    with SessionLocal() as db:
        assert channels.prefs(db, OWNER_HASH) == {"channels": ["telegram"], "mode": "first"}


def test_set_prefs_validates(chan):
    assert channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "all") == {"channels": ["wechat", "telegram"], "mode": "all"}
    with SessionLocal() as db:
        assert channels.prefs(db, OWNER_HASH) == {"channels": ["wechat", "telegram"], "mode": "all"}
    assert channels.set_prefs(OWNER_HASH, ["telegram"], "first")["mode"] == "first"  # a second save replaces
    for bad in (([], "first"), (["sms"], "first"), (["telegram", "telegram"], "first"), (["telegram"], "both"),
                (["telegram"], None)):
        with pytest.raises(ValueError, match="invalid_channels"):
            channels.set_prefs(OWNER_HASH, *bad)
    with SessionLocal() as db:
        assert channels.prefs(db, OWNER_HASH)["channels"] == ["telegram"]


def test_available_reads_only_the_presence_of_the_wechat_login(chan):
    _bind()
    bot = _bot()
    with SessionLocal() as db:
        assert channels.available(db, OWNER_HASH, "telegram", bot) is True
        assert channels.available(db, OWNER_HASH, "wechat", bot) is False
        chan["bot_token"] = "x"
        assert channels.available(db, OWNER_HASH, "wechat", bot) is False  # no owner id yet
        chan["owner_user_id"] = "y"
        assert channels.available(db, OWNER_HASH, "wechat", bot) is True
        assert channels.available(db, OTHER_HASH, "telegram", bot) is False
        assert channels.available(db, OWNER_HASH, "sms", bot) is False


# --- enqueue -----------------------------------------------------------------------------------------

def test_enqueue_without_prefs_is_todays_row(chan):
    _bind()
    chan.update(LOGIN)  # a connected WeChat changes nothing while no preference is stored
    left = _queue("【助理】\n有新消息")
    assert left == _bot().daily_notify_cap - 1
    [row] = _rows()
    assert (row.channel, row.group_id, row.status, row.text, row.telegram_bot_row_id) == (
        "telegram", None, "pending", "【助理】\n有新消息", None)
    assert row.acked_at is None and row.failure is None and row.attempts == 0


def test_enqueue_without_prefs_and_unbound_still_refuses(chan):
    chan.update(LOGIN)
    with pytest.raises(tg.NotifyError, match="telegram_not_bound"):
        _queue()
    assert _rows() == []


def test_first_mode_picks_the_first_available(chan):
    _bind()
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    _queue("【助理】\n甲")                       # WeChat not connected: Telegram
    chan.update(LOGIN)
    _queue("【助理】\n乙", now=NOW + timedelta(seconds=1))  # WeChat connected: WeChat only
    one, two = _rows()
    assert (one.channel, one.group_id, one.text) == ("telegram", None, "【助理】\n甲")
    assert (two.channel, two.group_id, two.text) == ("wechat", None, "【助理】\n乙")


def test_all_mode_fans_out_and_counts_once(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "all")
    left = _queue("【助理】\n全渠道")
    assert left == _bot().daily_notify_cap - 1
    rows = _rows()
    assert sorted(r.channel for r in rows) == ["telegram", "wechat"]
    assert rows[0].group_id is not None and rows[0].group_id == rows[1].group_id
    assert {r.text for r in rows} == {"【助理】\n全渠道"}   # WeChat keeps the name in front
    with SessionLocal() as db:
        assert tg.sent_today(db, OWNER_HASH, _bot().id, NOW) == 1
    # the next message sees one used, not two
    assert _queue("【助理】\n第二条", now=NOW + timedelta(seconds=1)) == _bot().daily_notify_cap - 2


def test_all_mode_with_one_channel_available_is_a_single_row_without_group(chan):
    _bind()
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "all")
    _queue()
    [row] = _rows()
    assert (row.channel, row.group_id) == ("telegram", None)


def test_the_bots_own_telegram_bot_drops_the_name_and_wechat_keeps_it(chan):
    from app.agent_chat_models import AgentTelegramBot
    bot = _bot()
    with SessionLocal() as db:
        db.query(AgentTelegramBot).delete()
        own = AgentTelegramBot(owner_hash=OWNER_HASH, bot_id=bot.id, token_cipher="c", token_fingerprint=uuid.uuid4().hex,
                               chat_id=CHAT, user_id=CHAT, status="bound")
        db.add(own)
        db.commit()
        own_id = own.id
    try:
        chan.update(LOGIN)
        channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "all")
        _queue(f"【{bot.name}】\n你好")
        by = {r.channel: r for r in _rows()}
        assert by["telegram"].text == "你好" and by["telegram"].telegram_bot_row_id == own_id
        assert by["wechat"].text == f"【{bot.name}】\n你好" and by["wechat"].telegram_bot_row_id is None
    finally:
        with SessionLocal() as db:
            db.query(AgentTelegramBot).delete()
            db.commit()


def test_no_channel_available_raises_telegram_not_bound(chan):
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "all")
    with pytest.raises(tg.NotifyError, match="telegram_not_bound"):
        _queue()
    assert _rows() == []


def test_channels_keyword_overrides_the_preference(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")
    bot = _bot()
    with SessionLocal() as db:
        tg.enqueue(db, OWNER_HASH, bot.id, "微信掉线了", source="alert", now=NOW, channels=["telegram"])
        db.commit()
    [row] = _rows()
    assert (row.channel, row.group_id) == ("telegram", None)
    # an override naming a channel that is not available is the same refusal as before
    with SessionLocal() as db:
        db.query(AgentTelegramBind).delete()
        db.commit()
    with SessionLocal() as db, pytest.raises(tg.NotifyError, match="telegram_not_bound"):
        tg.enqueue(db, OWNER_HASH, bot.id, "x", source="alert", now=NOW, channels=["telegram"])


def test_the_daily_cap_and_unknown_bot_errors_are_unchanged(chan):
    _bind()
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "all")
    chan.update(LOGIN)
    for n in range(_bot().daily_notify_cap):
        _queue(f"m{n}", now=NOW + timedelta(seconds=n))
    with pytest.raises(tg.NotifyError, match="notify_daily_cap"):
        _queue("one too many", now=NOW + timedelta(minutes=1))
    _queue("earnings are not capped", source="earnings", now=NOW + timedelta(minutes=1))
    with SessionLocal() as db, pytest.raises(tg.NotifyError, match="unknown_bot"):
        tg.enqueue(db, OWNER_HASH, uuid.uuid4(), "x", source="notify", now=NOW)


# --- the Telegram bridge's own calls ------------------------------------------------------------------

def test_telegram_calls_delegate_and_wechat_rows_are_not_in_the_telegram_queue(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "all")
    _queue("【助理】\n甲")
    [item] = tg.pending_messages(OWNER_HASH)
    assert item["text"] == "【助理】\n甲"
    assert [m["text"] for m in channels.pending(OWNER_HASH, "wechat")] == ["【助理】\n甲"]
    tg.mark_sent(item["id"], 4242)
    [sent] = _rows(channel="telegram")
    assert (sent.status, sent.telegram_message_id) == ("sent", 4242) and sent.sent_at is not None
    assert tg.pending_messages(OWNER_HASH) == []
    assert len(channels.pending(OWNER_HASH, "wechat")) == 1  # the other channel is untouched


def test_pending_is_oldest_first_and_limited(chan):
    _bind()
    for n in range(3):
        _plant("wechat", created=NOW + timedelta(seconds=n), text=f"w{n}")
    assert [m["text"] for m in channels.pending(OWNER_HASH, "wechat", limit=2)] == ["w0", "w1"]
    assert set(channels.pending(OWNER_HASH, "wechat")[0]) == {"id", "bot_id", "text", "source", "group_id"}


def test_pending_carries_the_source_and_the_group(chan):
    """5c-3b: the bridge puts the 「有用／没用」 row on a duty or brief message by its group (its own id when it has none)."""
    _bind()
    group = uuid.uuid4()
    _plant(source="duty", group=group, text="值班", created=NOW)
    _plant(source="brief", text="简报", created=NOW + timedelta(seconds=1))
    duty, brief = tg.pending_messages(OWNER_HASH)
    assert (duty["source"], duty["group_id"]) == ("duty", str(group))
    assert (brief["source"], brief["group_id"]) == ("brief", None)


# --- failure, fail-over, expiry ---------------------------------------------------------------------------

def test_third_failure_closes_the_row_and_fails_over_once(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    _queue("【助理】\n甲")
    [wx] = _rows(channel="wechat")
    for _ in range(tg.SEND_ATTEMPTS - 1):
        channels.mark_failed(wx.id)
    assert [r.channel for r in _rows()] == ["wechat"]          # still retrying, nothing re-queued yet
    channels.mark_failed(wx.id)
    rows = {r.channel: r for r in _rows()}
    assert (rows["wechat"].status, rows["wechat"].failure, rows["wechat"].attempts) == ("failed", "send_failed", 3)
    assert rows["telegram"].status == "pending" and rows["telegram"].text == "【助理】\n甲"
    assert rows["telegram"].group_id == rows["wechat"].group_id is not None
    assert (rows["telegram"].bot_id, rows["telegram"].source) == (rows["wechat"].bot_id, "notify")
    channels.mark_failed(wx.id)                                # a fourth call on the closed row adds nothing
    assert len(_rows()) == 2 and _rows(channel="wechat")[0].attempts == 3
    with SessionLocal() as db:                                  # and the failed-over message still counts once
        assert tg.sent_today(db, OWNER_HASH, _bot().id, NOW) == 1


def test_telegram_failures_through_the_old_entry_point_fail_over_too(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "first")
    _queue("【助理】\n甲")
    [item] = tg.pending_messages(OWNER_HASH)
    for _ in range(tg.SEND_ATTEMPTS):
        tg.mark_failed(item["id"])
    assert [m["text"] for m in channels.pending(OWNER_HASH, "wechat")] == ["【助理】\n甲"]
    assert tg.pending_messages(OWNER_HASH) == []


def test_a_failure_code_is_kept(chan):
    row = _plant("wechat", attempts=tg.SEND_ATTEMPTS - 1)
    channels.mark_failed(row, "expired")
    assert _rows(channel="wechat")[0].failure == "expired"
    other = _plant("wechat", attempts=tg.SEND_ATTEMPTS - 1)
    channels.mark_failed(other, "not_connected")                # no such code any more: the default one
    assert {str(r.id): r.failure for r in _rows(channel="wechat")}[other] == "send_failed"


def test_without_prefs_a_third_failure_just_closes_the_row(chan):
    _bind()
    chan.update(LOGIN)
    _queue()
    [item] = tg.pending_messages(OWNER_HASH)
    for _ in range(tg.SEND_ATTEMPTS):
        tg.mark_failed(item["id"])
    [row] = _rows()
    assert (row.status, row.failure, row.group_id) == ("failed", "send_failed", None)


def test_expire_stuck_fails_over_once_and_a_closed_row_is_not_pending(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    _queue("【助理】\n甲", now=NOW)
    later = NOW + timedelta(seconds=channels.STUCK_SECONDS + 1)
    assert channels.expire_stuck(OWNER_HASH, now=NOW + timedelta(seconds=channels.STUCK_SECONDS - 1)) == 0
    assert channels.expire_stuck(OWNER_HASH, now=later) == 1
    assert channels.expire_stuck(OWNER_HASH, now=later) == 0
    rows = {r.channel: r for r in _rows()}
    assert (rows["wechat"].status, rows["wechat"].failure) == ("failed", "expired")
    assert rows["telegram"].status == "pending" and len(rows) == 2
    assert channels.pending(OWNER_HASH, "wechat") == []        # never sent later, even if the bridge comes back
    assert len(channels.pending(OWNER_HASH, "telegram")) == 1


def test_expire_stuck_from_two_sessions_at_once_adds_one_row(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    _queue("【助理】\n甲", now=NOW)
    later = NOW + timedelta(seconds=channels.STUCK_SECONDS + 1)
    with ThreadPoolExecutor(2) as pool:
        closed = list(pool.map(lambda _: channels.expire_stuck(OWNER_HASH, now=later), range(2)))
    assert sum(closed) == 1
    assert sorted(r.channel for r in _rows()) == ["telegram", "wechat"]


def test_expire_stuck_leaves_other_owners_and_replies_alone(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    stray = AgentTelegramMessage(owner_hash=OTHER_HASH, source="notify", text="x", status="pending", channel="wechat",
                                 created_at=NOW)
    with SessionLocal() as db:
        db.add(stray)
        db.commit()
    _plant("telegram", status="sent", source="reply", created=NOW)
    assert channels.expire_stuck(OWNER_HASH, now=NOW + timedelta(hours=1)) == 0
    assert _rows(owner_hash=OTHER_HASH)[0].status == "pending"


def test_a_stuck_row_with_nowhere_to_go_stays_pending(chan):
    _bind()
    old = NOW - timedelta(minutes=10)
    row = _plant("telegram", created=old)                       # default prefs: Telegram only
    assert channels.expire_stuck(OWNER_HASH, now=NOW) == 0
    assert (_rows(channel="telegram")[0].status, _rows(channel="telegram")[0].failure) == ("pending", None)
    assert [m["id"] for m in channels.pending(OWNER_HASH, "telegram")] == [row]
    # WeChat first, Telegram not available: the stuck wechat row stays too
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    chan.update(LOGIN)
    wx_row = _plant("wechat", created=old)
    with SessionLocal() as db:
        db.query(AgentTelegramBind).delete()
        db.commit()
    assert channels.expire_stuck(OWNER_HASH, now=NOW) == 0
    assert {str(r.id): r.status for r in _rows(channel="wechat")}[wx_row] == "pending"
    # once Telegram is available again the next sweep fails it over
    _bind()
    assert channels.expire_stuck(OWNER_HASH, now=NOW) == 1
    assert {str(r.id): r.status for r in _rows(channel="wechat")}[wx_row] == "failed"


def test_a_claimed_row_is_not_expired_until_the_lease_runs_out(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    now = NOW + timedelta(minutes=10)
    fresh = _plant("wechat", created=NOW, claimed=now - timedelta(seconds=10))
    assert channels.expire_stuck(OWNER_HASH, now=now) == 0
    assert _rows(channel="wechat")[0].status == "pending"
    with SessionLocal() as db:
        db.get(AgentTelegramMessage, uuid.UUID(fresh)).claimed_at = now - timedelta(minutes=5)
        db.commit()
    assert channels.expire_stuck(OWNER_HASH, now=now) == 1
    assert _rows(channel="wechat")[0].status == "failed"


def test_pending_claims_the_rows_it_returns_and_reclaims_on_each_call(chan):
    _bind()
    _plant("telegram", created=NOW)
    first, second = NOW + timedelta(seconds=5), NOW + timedelta(seconds=40)
    assert len(channels.pending(OWNER_HASH, "telegram", now=first)) == 1
    assert _rows()[0].claimed_at == first
    assert len(tg.pending_messages(OWNER_HASH)) == 1           # the Telegram entry point claims too
    channels.pending(OWNER_HASH, "telegram", now=second)
    assert _rows()[0].claimed_at == second
    assert channels.pending(OWNER_HASH, "wechat", now=second) == []


def test_a_bridge_that_claimed_a_row_and_died_lets_it_expire(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    _plant("wechat", created=NOW)
    channels.pending(OWNER_HASH, "wechat", now=NOW + timedelta(seconds=400))
    assert channels.expire_stuck(OWNER_HASH, now=NOW + timedelta(seconds=450)) == 0      # claimed 50 s ago
    assert channels.expire_stuck(OWNER_HASH, now=NOW + timedelta(seconds=400 + channels.CLAIM_SECONDS + 5)) == 1  # lease over


def test_a_closed_row_cannot_be_marked_sent_even_if_it_was_expired(chan):
    row = _plant("telegram", status="failed", failure="expired")
    channels.mark_sent(row, 9)
    assert (_rows(channel="telegram")[0].status, _rows(channel="telegram")[0].failure) == ("failed", "expired")


def test_a_row_closed_for_failures_cannot_be_marked_sent_afterwards(chan):
    row = _plant("telegram", attempts=tg.SEND_ATTEMPTS - 1)
    channels.mark_failed(row)
    channels.mark_sent(row, 9)
    assert _rows(channel="telegram")[0].status == "failed"


def test_no_fail_over_when_the_other_channel_already_has_the_message(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "all")
    _queue("【助理】\n甲")
    [wx] = _rows(channel="wechat")
    for _ in range(tg.SEND_ATTEMPTS):
        channels.mark_failed(wx.id)
    assert len(_rows()) == 2
    assert _rows(channel="telegram")[0].status == "pending"


def test_fail_over_goes_only_to_a_listed_and_available_channel(chan):
    _bind()
    row = _plant("wechat", attempts=tg.SEND_ATTEMPTS - 1)
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")           # Telegram is not listed
    channels.mark_failed(row)
    assert len(_rows()) == 1
    row = _plant("wechat", attempts=tg.SEND_ATTEMPTS - 1)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    with SessionLocal() as db:
        tg_row = db.get(AgentTelegramMessage, uuid.UUID(row))
        db.delete(db.query(AgentTelegramMessage).filter(AgentTelegramMessage.id != tg_row.id).first())
        db.commit()
    with SessionLocal() as db:
        db.query(AgentTelegramBind).delete()                      # ... and not bound: nowhere to go
        db.commit()
    channels.mark_failed(row)
    assert [r.channel for r in _rows()] == ["wechat"]


# --- acknowledgement and the delivery list ---------------------------------------------------------------

def test_acknowledge_marks_only_that_channel(chan):
    ack = NOW + timedelta(minutes=5)
    sent_tg = _plant("telegram", status="sent", sent=NOW)
    sent_wx = _plant("wechat", status="sent", sent=NOW)
    pending_wx = _plant("wechat", status="pending")
    assert channels.acknowledge(OWNER_HASH, "wechat", now=ack) == 1
    assert channels.acknowledge(OWNER_HASH, "wechat", now=ack + timedelta(minutes=1)) == 0   # already acked
    by = {str(r.id): r for r in _rows()}
    assert by[sent_wx].acked_at == ack
    assert by[sent_tg].acked_at is None and by[pending_wx].acked_at is None
    assert channels.acknowledge(OWNER_HASH, "telegram", now=ack) == 1
    assert channels.acknowledge(OTHER_HASH, "telegram", now=ack) == 0


def test_acknowledge_skips_replies_and_does_not_backfill_old_history(chan):
    ack = NOW + timedelta(days=10)
    old = _plant("telegram", status="sent", sent=NOW)                                  # 10 days old
    reply = _plant("telegram", status="sent", source="reply", sent=ack - timedelta(minutes=1))
    recent = _plant("telegram", status="sent", sent=ack - timedelta(days=6))
    assert channels.acknowledge(OWNER_HASH, "telegram", now=ack) == 1
    by = {str(r.id): r for r in _rows()}
    assert by[recent].acked_at == ack
    assert by[old].acked_at is None and by[reply].acked_at is None


def test_deliveries_lists_proactive_rows_newest_first_without_replies(chan):
    _plant("telegram", status="sent", created=NOW, text="old")
    _plant("telegram", status="sent", source="reply", created=NOW + timedelta(seconds=1), text="an answer")
    group = uuid.uuid4()
    _plant("wechat", status="failed", created=NOW + timedelta(seconds=2), group=group, text="长" * 200)
    with SessionLocal() as db:
        db.add(AgentTelegramMessage(owner_hash=OTHER_HASH, source="notify", text="not mine", status="sent", created_at=NOW))
        db.commit()
    items = channels.deliveries(OWNER_HASH)
    assert [i["channel"] for i in items] == ["wechat", "telegram"]
    first = items[0]
    assert set(first) == {"id", "group_id", "bot_id", "source", "channel", "status", "failure", "created_at", "sent_at",
                          "acked_at", "text"}
    assert len(first["text"]) == 120 and first["group_id"] == str(group)
    assert items[1]["text"] == "old" and items[1]["group_id"] is None
    assert len(channels.deliveries(OWNER_HASH, limit=1)) == 1


def test_daily_cap_counts_a_failed_over_message_once(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    _queue("甲", now=NOW)
    [wx] = _rows(channel="wechat")
    for _ in range(tg.SEND_ATTEMPTS):
        channels.mark_failed(wx.id)
    assert len(_rows()) == 2
    with SessionLocal() as db:
        assert tg.sent_today(db, OWNER_HASH, _bot().id, NOW + timedelta(seconds=1)) == 1
    # plain rows from before the migration (no group) still count one each
    _plant("telegram", created=NOW)
    _plant("telegram", created=NOW)
    with SessionLocal() as db:
        assert tg.sent_today(db, OWNER_HASH, _bot().id, NOW) == 3


def test_replies_are_not_counted_and_keep_working(chan):
    _bind()
    tg.record_reply(OWNER_HASH, _bot().id, "answer", 55)
    [row] = _rows()
    assert (row.source, row.status, row.channel) == ("reply", "sent", "telegram")
    with SessionLocal() as db:
        assert tg.sent_today(db, OWNER_HASH, _bot().id, NOW) == 0
    assert tg.route(OWNER_HASH, "re", reply_to_message_id=55)["via"] == "reply"


# --- schema ------------------------------------------------------------------------------------------

def test_ensure_columns_is_idempotent(chan):
    from sqlalchemy import inspect
    from app.database import engine
    tg.ensure_columns()
    tg.ensure_columns()
    columns = {c["name"]: c for c in inspect(engine).get_columns("agent_telegram_messages")}
    assert {"channel", "group_id", "acked_at", "failure"} <= set(columns)
    assert columns["channel"]["nullable"] is False
    assert {c["name"] for c in inspect(engine).get_columns("agent_channel_prefs")} == {
        "owner_hash", "channels", "mode", "updated_at"}


def test_ensure_columns_upgrades_an_old_outbox_table(chan):
    from sqlalchemy import inspect, text
    from app.database import engine
    with engine.begin() as connection:
        for column in ("channel", "group_id", "acked_at", "failure"):
            connection.execute(text(f"ALTER TABLE agent_telegram_messages DROP COLUMN {column}"))
        connection.execute(text("DROP TABLE agent_channel_prefs"))
        connection.execute(text("INSERT INTO agent_telegram_messages (id, owner_hash, source, text, status, attempts, created_at) "
                                "VALUES (gen_random_uuid(), 'old', 'notify', 't', 'pending', 0, now())"))
    tg.ensure_columns()
    assert {"channel", "group_id", "acked_at", "failure"} <= {c["name"] for c in inspect(engine).get_columns("agent_telegram_messages")}
    with SessionLocal() as db:
        old = db.query(AgentTelegramMessage).filter_by(owner_hash="old").one()
        assert old.channel == "telegram" and old.group_id is None
        db.delete(old)
        db.commit()
        assert channels.prefs(db, OWNER_HASH) == {"channels": ["telegram"], "mode": "first"}


# --- the stale-login notice -----------------------------------------------------------------------------

def test_the_wechat_stale_notice_never_goes_to_wechat(chan, monkeypatch):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "all")
    from scripts import run_wechat_bridge as wb
    wb._notify_stale(OWNER_HASH)
    [row] = _rows()
    assert (row.channel, row.source, row.text) == ("telegram", "alert", wb.STALE_ALERT)


# --- endpoints ---------------------------------------------------------------------------------------

def test_endpoint_get_reports_prefs_and_availability(chan, client):
    _bind()
    got = client.get("/agent-chat/channels", headers=H)
    assert got.status_code == 200
    assert got.json() == {"prefs": {"channels": ["telegram"], "mode": "first"},
                          "available": {"telegram": True, "wechat": False}}
    chan.update(LOGIN)
    body = client.get("/agent-chat/channels", headers=H).json()
    assert body["available"]["wechat"] is True
    assert "wx-token" not in str(body) and "wx-owner" not in str(body)


def test_endpoint_put_valid_and_invalid(chan, client):
    put = client.put("/agent-chat/channels", headers=H, json={"channels": ["wechat", "telegram"], "mode": "all"})
    assert put.status_code == 200 and put.json() == {"channels": ["wechat", "telegram"], "mode": "all"}
    assert client.get("/agent-chat/channels", headers=H).json()["prefs"] == put.json()
    for bad in ({"channels": [], "mode": "first"}, {"channels": ["sms"], "mode": "first"},
                {"channels": ["telegram"], "mode": "both"}, {"channels": ["telegram", "telegram"], "mode": "first"}):
        assert client.put("/agent-chat/channels", headers=H, json=bad).status_code == 400
    assert client.get("/agent-chat/channels", headers=H).json()["prefs"] == put.json()


def test_endpoints_refuse_a_guest(chan, client):
    assert client.get("/agent-chat/channels", headers=GUEST).status_code == 403
    assert client.put("/agent-chat/channels", headers=GUEST, json={"channels": ["telegram"], "mode": "first"}).status_code == 403
    assert client.get("/agent-chat/channels/deliveries", headers=GUEST).status_code == 403


def test_endpoint_deliveries(chan, client):
    _plant("wechat", status="sent", created=NOW, text="hello")
    _plant("telegram", status="sent", source="reply", created=NOW)
    body = client.get("/agent-chat/channels/deliveries?limit=10", headers=H).json()
    assert [(i["channel"], i["text"]) for i in body["items"]] == [("wechat", "hello")]


def test_a_stale_wechat_login_is_not_available(chan):
    _bind()
    bot = _bot()
    chan.update(LOGIN)
    with SessionLocal() as db:
        assert channels.available(db, OWNER_HASH, "wechat", bot) is True
        chan["stale_since"] = 1_700_000_000.0
        assert channels.available(db, OWNER_HASH, "wechat", bot) is False
        channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
        assert channels.targets(db, OWNER_HASH, bot) == ["telegram"]       # no five-minute wait on a dead login
        chan.pop("stale_since")
        assert channels.targets(db, OWNER_HASH, bot) == ["wechat"]


# --- final fix wave ---------------------------------------------------------------------------------

def test_a_stuck_row_is_closed_without_fail_over_when_the_message_reached_the_owner_elsewhere(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "all")
    _queue("【助理】\n甲", now=NOW)
    [tg_row] = _rows(channel="telegram")
    channels.mark_sent(tg_row.id, 5)
    later = NOW + timedelta(minutes=10)
    assert channels.expire_stuck(OWNER_HASH, now=later) == 1
    rows = {r.channel: r for r in _rows()}
    assert len(rows) == 2 and (rows["wechat"].status, rows["wechat"].failure) == ("failed", "expired")
    assert channels.pending(OWNER_HASH, "wechat") == []


def test_when_nothing_was_delivered_both_stuck_rows_stay_pending(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "all")
    _queue("【助理】\n甲", now=NOW)
    assert channels.expire_stuck(OWNER_HASH, now=NOW + timedelta(minutes=10)) == 0
    assert sorted((r.channel, r.status) for r in _rows()) == [("telegram", "pending"), ("wechat", "pending")]


def test_a_partly_sent_sibling_does_not_count_as_delivered(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    _queue("【助理】\n甲", now=NOW)
    [wx] = _rows(channel="wechat")
    channels.mark_partial(wx.id)
    assert channels.expire_stuck(OWNER_HASH, now=datetime.now(UTC) + timedelta(minutes=10)) == 0   # Telegram holds the full text
    assert _rows(channel="telegram")[0].status == "pending"


def test_mark_partial_keeps_the_row_sent_and_sends_the_full_text_on_the_next_channel(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    _queue("【助理】\n很长的消息", now=NOW)
    [wx] = _rows(channel="wechat")
    channels.mark_partial(wx.id)
    rows = {r.channel: r for r in _rows()}
    assert (rows["wechat"].status, rows["wechat"].failure) == ("sent", "partial") and rows["wechat"].sent_at is not None
    assert rows["telegram"].status == "pending" and rows["telegram"].text == "【助理】\n很长的消息"
    assert rows["telegram"].group_id == rows["wechat"].group_id is not None
    channels.mark_partial(wx.id)                                 # a second call on the closed row adds nothing
    assert len(_rows()) == 2
    item = {i["channel"]: i for i in channels.deliveries(OWNER_HASH)}["wechat"]
    assert (item["status"], item["failure"]) == ("sent", "partial")
    with SessionLocal() as db:
        assert tg.sent_today(db, OWNER_HASH, _bot().id, NOW) == 1


def test_mark_partial_without_another_channel_adds_no_row(chan):
    _bind()
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")          # no other channel is listed
    row = _plant("wechat")
    channels.mark_partial(row)
    [only] = _rows()
    assert (only.status, only.failure) == ("sent", "partial")


def test_claim_restamps_one_pending_row(chan):
    row = _plant("wechat", created=NOW, claimed=NOW)
    other = _plant("wechat", created=NOW, claimed=NOW)
    stamp = NOW + timedelta(seconds=120)
    channels.claim(row, now=stamp)
    by = {str(r.id): r for r in _rows()}
    assert by[row].claimed_at == stamp and by[other].claimed_at == NOW
    closed = _plant("wechat", status="failed", failure="expired")
    channels.claim(closed, now=stamp)
    assert {str(r.id): r for r in _rows()}[closed].claimed_at is None
    assert channels.CLAIM_SECONDS == 180


def test_acknowledge_with_seen_at_skips_rows_sent_after_the_message(chan):
    seen = NOW + timedelta(hours=1)
    before = _plant("telegram", status="sent", sent=seen - timedelta(minutes=5))
    after = _plant("telegram", status="sent", sent=seen + timedelta(minutes=5))
    assert channels.acknowledge(OWNER_HASH, "telegram", seen_at=seen) == 1
    by = {str(r.id): r for r in _rows()}
    assert by[before].acked_at == seen and by[after].acked_at is None
