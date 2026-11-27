import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts import selfcheck_replay
from tests.test_agent_notify import OWNER, OWNER_HASH

SHADOW = "postgresql://u@h/finbot_ruler"


def test_it_refuses_without_the_shadow_database():
    assert "RULER_DATABASE_URL" in selfcheck_replay.refusal({"DATABASE_URL": "postgresql://live"})


def test_it_refuses_when_the_database_is_not_the_shadow_one():
    assert "不是影子库" in selfcheck_replay.refusal({"RULER_DATABASE_URL": SHADOW, "DATABASE_URL": "postgresql://live"})


def test_it_refuses_a_database_not_named_finbot_ruler_even_when_both_variables_match():
    url = "postgresql://u@h/finbot"
    assert "finbot_ruler" in selfcheck_replay.refusal({"RULER_DATABASE_URL": url, "DATABASE_URL": url})


def test_it_runs_on_the_shadow_database():
    assert selfcheck_replay.refusal({"RULER_DATABASE_URL": SHADOW, "DATABASE_URL": SHADOW}) is None


def test_main_exits_2_before_touching_anything_outside_the_shadow(monkeypatch, capsys):
    from app.kernel import selfcheck
    monkeypatch.delenv("RULER_DATABASE_URL", raising=False)
    monkeypatch.setattr(selfcheck, "run_once", lambda *a, **k: pytest.fail("ran outside the shadow"))
    assert selfcheck_replay.main(["--day", "2026-11-28"]) == 2
    assert "RULER_DATABASE_URL" in capsys.readouterr().err


@pytest.fixture
def shadow(monkeypatch, tmp_path):
    """main() past its guard, with the check and the database reads replaced."""
    from app import agent_task_runner as runner
    from app import duty_selfcheck
    from app.kernel import selfcheck
    seen = {}

    def fake_run_once(owner_hash, now, *, day=None, since=None, sentinel_db=None, snapshot=None, fetch=None):
        import os
        seen.update(owner=owner_hash, now=now, day=day, since=since, sentinel_db=sentinel_db, snapshot=snapshot,
                    mode=os.environ.get("FINBOT_DUTY_MODE"))
        return {"day": day, "outcome": "done", "findings": [], "checked": {}}

    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"positions": [{"symbol": "NVDA", "shares": 10}]}), encoding="utf-8")
    monkeypatch.setattr(selfcheck_replay, "refusal", lambda environ=None: None)
    monkeypatch.setattr(selfcheck_replay, "DEFAULT_SNAPSHOT", snap)
    monkeypatch.setattr(runner, "owner_credential", lambda: OWNER)
    monkeypatch.setattr(duty_selfcheck, "get", lambda owner_hash, day: None)
    monkeypatch.setattr(selfcheck, "run_once", fake_run_once)
    monkeypatch.setenv("FINBOT_DUTY_MODE", "off")
    return seen


def test_main_forces_shadow_and_passes_the_day_the_instant_and_the_window(shadow, tmp_path, capsys):
    db = tmp_path / "sentinel.db"
    code = selfcheck_replay.main(["--day", "2026-11-28", "--now", "2026-11-26T00:00:00+00:00", "--since-hours", "400",
                                  "--sentinel-db", str(db), "--snapshot", str(selfcheck_replay.DEFAULT_SNAPSHOT)])
    assert code == 0 and shadow["mode"] == "shadow" and shadow["day"] == "2026-11-28" and shadow["owner"] == OWNER_HASH
    assert shadow["now"] == datetime(2026, 11, 26, tzinfo=UTC) and shadow["now"] - shadow["since"] == timedelta(hours=400)
    assert shadow["sentinel_db"] == db and shadow["snapshot"] == {"positions": [{"symbol": "NVDA", "shares": 10}]}
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == "done" and printed["day"] == "2026-11-28"


def test_by_default_it_reads_the_source_trees_own_data_copy(shadow, monkeypatch):
    assert selfcheck_replay.main(["--day", "2026-11-28"]) == 0
    assert shadow["sentinel_db"] == selfcheck_replay.ROOT / "data" / "sentinel.db" and shadow["since"] is None
    assert abs(datetime.now(UTC) - shadow["now"]) < timedelta(minutes=1)


def test_without_a_day_outside_the_morning_it_asks_for_one(shadow, monkeypatch, capsys):
    from app.kernel import selfcheck
    monkeypatch.setattr(selfcheck, "due_day", lambda now: None)
    assert selfcheck_replay.main([]) == 2 and "--day" in capsys.readouterr().err and "day" not in shadow


def test_a_day_that_already_has_a_check_is_refused(shadow, monkeypatch, capsys):
    from app import duty_selfcheck
    monkeypatch.setattr(duty_selfcheck, "get", lambda owner_hash, day: {"day": day, "outcome": "done"})
    assert selfcheck_replay.main(["--day", "2026-11-28"]) == 2 and "--day" in capsys.readouterr().err and "day" not in shadow


def test_a_bad_day_or_a_naive_instant_is_an_argument_error():
    with pytest.raises(SystemExit):
        selfcheck_replay.main(["--day", "11/28"])
    with pytest.raises(SystemExit):
        selfcheck_replay.main(["--now", "2026-11-26T00:00:00"])
