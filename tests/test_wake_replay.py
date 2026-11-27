import sqlite3

import pytest

from scripts import wake_replay


def test_it_refuses_without_the_shadow_database():
    assert "RULER_DATABASE_URL" in wake_replay.refusal({"DATABASE_URL": "postgresql://live"})


def test_it_refuses_when_the_database_is_not_the_shadow_one():
    assert "不是影子库" in wake_replay.refusal({"RULER_DATABASE_URL": "postgresql://u@h/finbot_ruler", "DATABASE_URL": "postgresql://live"})


def test_it_refuses_a_database_not_named_finbot_ruler_even_when_both_variables_match():
    url = "postgresql://u@h/finbot"
    assert "finbot_ruler" in wake_replay.refusal({"RULER_DATABASE_URL": url, "DATABASE_URL": url})


def test_it_runs_on_the_shadow_database():
    url = "postgresql://u@h/finbot_ruler"
    assert wake_replay.refusal({"RULER_DATABASE_URL": url, "DATABASE_URL": url}) is None


def test_main_exits_2_before_touching_anything_outside_the_shadow(monkeypatch, capsys):
    monkeypatch.delenv("RULER_DATABASE_URL", raising=False)
    assert wake_replay.main(["--sentinel-db", "/nonexistent.db", "--alert", "1"]) == 2
    assert "RULER_DATABASE_URL" in capsys.readouterr().err


def _sentinel(tmp_path):
    path = tmp_path / "sentinel.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY, symbol TEXT, kind TEXT, text TEXT, escalate INTEGER, created_at REAL, deferred INTEGER)")
    db.execute("INSERT INTO alerts VALUES (59, 'NVDA', 'daily', '【盘前异动】NVDA 较昨收涨 19.5%', 0, 1795442237.5, 0)")
    db.commit()
    db.close()
    return str(path)


def test_the_event_is_the_alert_under_an_offset_id_with_the_tier_set_by_hand(tmp_path):
    event = wake_replay.event_from(_sentinel(tmp_path), 59, offset=900_000_000, tier=2, sigma=4.9, held=False)
    assert event["alert_id"] == 900_000_059 and event["replay_of"] == 59
    assert event["symbol"] == "NVDA" and event["tier"] == 2 and event["sigma_mult"] == 4.9 and event["held"] is False
    assert event["text"].startswith("【盘前异动】")


def test_no_tier_is_added_unless_asked(tmp_path):
    event = wake_replay.event_from(_sentinel(tmp_path), 59, offset=0, tier=None, sigma=None, held=True)
    assert "tier" not in event and "sigma_mult" not in event and event["held"] is True


def test_a_missing_alert_is_a_message(tmp_path):
    with pytest.raises(LookupError, match="#60"):
        wake_replay.event_from(_sentinel(tmp_path), 60, offset=0, tier=None, sigma=None, held=False)



def test_a_stored_call_is_named_from_its_function():
    assert wake_replay.call_name({"id": "t1", "type": "function", "function": {"name": "query_stock_prices", "arguments": "{}"}}) == "query_stock_prices"
    assert wake_replay.call_name({"name": "decide"}) == "decide"
    assert wake_replay.call_name("junk") is None and wake_replay.call_name({}) is None
