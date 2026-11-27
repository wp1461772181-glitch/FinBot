"""5c-2b: the sentinel's alerts reach WeChat too (app/sentinel_copy.py).

When the owner's channel preference puts WeChat first, or asks for every channel, an alert the sentinel posted is queued once on WeChat
(source ``sentinel``).  Never for a night-held alert, never without a WeChat login, never twice for one alert id; the bot's notify cap
does not apply, and nothing here ever raises."""
import pytest

from app import agent_bots as bots
from app import agent_telegram as tg
from app import agent_wechat, channels, sentinel_copy
from app.agent_chat_models import AgentChannelPref, AgentTelegramMessage
from app.database import SessionLocal
from app.kernel import wake
from tests.test_agent_notify import NOW, OWNER_HASH, owner, _bind  # noqa: F401  (fixture)

LOGIN = {"bot_token": "wx-token-not-a-secret", "owner_user_id": "wx-owner"}
TEXT = "【盘中异动】AAPL 跌 4.4%"


@pytest.fixture
def chan(owner, monkeypatch):
    with SessionLocal() as db:
        db.query(AgentChannelPref).delete()
        db.query(sentinel_copy.SentinelCopy).delete()
        db.commit()
    state = {}
    monkeypatch.setattr(agent_wechat, "load_state", lambda path=None: dict(state))
    return state  # a test connects WeChat with state.update(LOGIN)


def alert(alert_id=1, **extra):
    return wake.clean_event({"alert_id": alert_id, "symbol": "AAPL", "kind": "daily", "text": TEXT, "deferred": False, "held": True, **extra})


def copy(event=None):
    return sentinel_copy.copy_to_wechat(OWNER_HASH, event or alert())


def _outbox(**where):
    with SessionLocal() as db:
        rows = db.query(AgentTelegramMessage).filter_by(**where).order_by(AgentTelegramMessage.created_at).all()
        for row in rows:
            db.expunge(row)
        return rows


def _copies():
    with SessionLocal() as db:
        return [sentinel_copy.as_dict(r) for r in db.query(sentinel_copy.SentinelCopy).order_by(sentinel_copy.SentinelCopy.alert_id)]


# --- when a copy is wanted (every row of the plan's table) ------------------------------------------------------------------

@pytest.mark.parametrize("listed, mode, expected", [
    (["telegram"], "first", False),                 # the default: Telegram already has it
    (["telegram"], "all", False),                   # WeChat not listed at all
    (["telegram", "wechat"], "first", False),       # WeChat only as the fallback
    (["wechat"], "first", True),                    # he reads WeChat first
    (["wechat", "telegram"], "first", True),
    (["wechat"], "all", True),                      # every channel
    (["telegram", "wechat"], "all", True),
    (["wechat", "telegram"], "all", True),
])
def test_wanted_follows_the_preference(listed, mode, expected):
    assert sentinel_copy.wanted({"channels": listed, "mode": mode}) is expected


def test_wanted_on_the_stored_default(chan):
    with SessionLocal() as db:
        assert sentinel_copy.wanted(channels.prefs(db, OWNER_HASH)) is False


# --- the copy -----------------------------------------------------------------------------------------------------------

def test_wechat_first_queues_one_wechat_row_with_the_alert_text(chan):
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")
    result = copy()
    assert result["outcome"] == "queued" and result["alert_id"] == 1 and result["group_id"]
    [row] = _outbox()
    assert (row.channel, row.source, row.status) == ("wechat", "sentinel", "pending")
    assert TEXT in row.text and row.text.startswith(f"【{bots.ensure_default_bot(OWNER_HASH).name}】")
    assert str(row.group_id) == result["group_id"]
    assert [(c["alert_id"], c["outcome"]) for c in _copies()] == [(1, "queued")]


def test_wechat_then_telegram_first_copies_to_wechat_only(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat", "telegram"], "first")
    assert copy()["outcome"] == "queued"
    assert [r.channel for r in _outbox()] == ["wechat"]


@pytest.mark.parametrize("listed", [["telegram", "wechat"], ["wechat", "telegram"], ["wechat"]])
def test_mode_all_copies_to_wechat_and_never_adds_a_telegram_row(chan, listed):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, listed, "all")
    assert copy()["outcome"] == "queued"
    assert [r.channel for r in _outbox()] == ["wechat"]      # Telegram has the alert from the sentinel itself


def test_the_default_preference_copies_nothing_and_writes_no_row(chan):
    _bind()
    chan.update(LOGIN)                                        # a connected WeChat changes nothing while Telegram is the preference
    assert copy() == {"outcome": "skipped_unwanted"}
    assert _outbox() == [] and _copies() == []


def test_wechat_as_the_fallback_copies_nothing(chan):
    _bind()
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["telegram", "wechat"], "first")
    assert copy() == {"outcome": "skipped_unwanted"}
    assert _outbox() == [] and _copies() == []


def test_a_night_held_alert_is_not_copied(chan):
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")
    assert copy(alert(deferred=True))["outcome"] == "skipped_deferred"
    assert _outbox() == []
    assert [(c["alert_id"], c["outcome"], c["group_id"]) for c in _copies()] == [(1, "skipped_deferred", None)]


def test_without_a_wechat_login_nothing_is_queued(chan):
    channels.set_prefs(OWNER_HASH, ["wechat"], "all")         # no login saved
    assert copy(alert(1))["outcome"] == "skipped_unavailable"
    chan.update(LOGIN, stale_since=1_700_000_000.0)           # a login that needs a new scan is not available either
    assert copy(alert(2))["outcome"] == "skipped_unavailable"
    assert _outbox() == []
    assert [(c["alert_id"], c["outcome"]) for c in _copies()] == [(1, "skipped_unavailable"), (2, "skipped_unavailable")]


def test_the_same_alert_id_twice_is_one_outbox_row(chan):
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")
    first = copy(alert(7))
    second = copy(alert(7, text="【盘中异动】AAPL 又跌"))     # a re-posted night line, a re-delivered event
    assert first["outcome"] == second["outcome"] == "queued" and first["group_id"] == second["group_id"]
    assert len(_outbox()) == 1 and len(_copies()) == 1
    assert copy(alert(8))["outcome"] == "queued"              # another alert is copied
    assert len(_outbox()) == 2


def test_a_full_notify_cap_does_not_stop_the_copy(chan, monkeypatch):
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")
    bot = bots.ensure_default_bot(OWNER_HASH)
    monkeypatch.setattr(tg, "sent_today", lambda *args: bot.daily_notify_cap)      # today's cap is used up, whatever the clock says
    with SessionLocal() as db, pytest.raises(tg.NotifyError, match="notify_daily_cap"):
        tg.enqueue(db, OWNER_HASH, bot.id, "one too many", source="notify", now=NOW)
    assert "sentinel" in tg.UNCAPPED
    assert copy()["outcome"] == "queued"
    assert [r.source for r in _outbox()] == ["sentinel"]


def test_an_error_inside_is_failed_and_never_raises(chan, monkeypatch):
    chan.update(LOGIN)
    channels.set_prefs(OWNER_HASH, ["wechat"], "first")
    real, broken = tg.enqueue, [True]

    def flaky(*args, **kwargs):
        if broken:
            broken.pop()
            raise RuntimeError("outbox down")
        return real(*args, **kwargs)
    monkeypatch.setattr(tg, "enqueue", flaky)
    assert copy() == {"outcome": "failed"}
    assert _outbox() == [] and _copies() == []                # rolled back: a re-post tries again
    assert copy()["outcome"] == "queued"
    assert len(_outbox()) == 1


def test_a_malformed_event_is_failed_and_never_raises(chan):
    assert sentinel_copy.copy_to_wechat(OWNER_HASH, {"text": TEXT}) == {"outcome": "failed"}
    assert sentinel_copy.copy_to_wechat(OWNER_HASH, None) == {"outcome": "failed"}
