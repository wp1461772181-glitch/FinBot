import json
from datetime import UTC, datetime, timedelta

import pytest

from app import duty_log
from scripts import brief_replay
from tests.test_agent_notify import OWNER, OWNER_HASH, owner  # noqa: F401  (fixture)

SHADOW = "postgresql://u@h/finbot_ruler"


def test_it_refuses_without_the_shadow_database():
    assert "RULER_DATABASE_URL" in brief_replay.refusal({"DATABASE_URL": "postgresql://live"})


def test_it_refuses_when_the_database_is_not_the_shadow_one():
    assert "不是影子库" in brief_replay.refusal({"RULER_DATABASE_URL": SHADOW, "DATABASE_URL": "postgresql://live"})


def test_it_refuses_a_database_not_named_finbot_ruler_even_when_both_variables_match():
    url = "postgresql://u@h/finbot"
    assert "finbot_ruler" in brief_replay.refusal({"RULER_DATABASE_URL": url, "DATABASE_URL": url})


def test_it_runs_on_the_shadow_database():
    assert brief_replay.refusal({"RULER_DATABASE_URL": SHADOW, "DATABASE_URL": SHADOW}) is None


def test_main_exits_2_before_touching_anything_outside_the_shadow(monkeypatch, capsys):
    from app.kernel import brief
    monkeypatch.delenv("RULER_DATABASE_URL", raising=False)
    monkeypatch.setattr(brief, "run_once", lambda *a, **k: pytest.fail("ran outside the shadow"))
    assert brief_replay.main(["--write-sample", "--day", "2026-11-28"]) == 2
    assert "RULER_DATABASE_URL" in capsys.readouterr().err


@pytest.fixture
def shadow(monkeypatch):
    """main() past its guard, with the brief and the database reads replaced."""
    from app import agent_task_runner as runner
    from app import duty_brief
    from app.kernel import brief
    seen = {}

    async def fake_run_once(owner_hash, now, *, day=None, since=None):
        import os
        seen.update(owner=owner_hash, now=now, day=day, since=since, mode=os.environ.get("FINBOT_DUTY_MODE"))
        return {"day": day, "outcome": "done", "message": "【早间简报】……"}

    monkeypatch.setattr(brief_replay, "refusal", lambda environ=None: None)
    monkeypatch.setattr(runner, "owner_credential", lambda: OWNER)
    monkeypatch.setattr(duty_brief, "get", lambda owner_hash, day: None)
    monkeypatch.setattr(brief, "run_once", fake_run_once)
    monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    return seen


def test_main_forces_shadow_and_passes_the_day_and_the_window(shadow, capsys):
    assert brief_replay.main(["--day", "2026-11-28", "--since-hours", "6"]) == 0
    assert shadow["mode"] == "shadow" and shadow["day"] == "2026-11-28" and shadow["owner"] == OWNER_HASH
    assert abs((shadow["now"] - shadow["since"]) - timedelta(hours=6)) < timedelta(seconds=1)
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == "done" and printed["day"] == "2026-11-28" and printed["sample_alert_ids"] == []


def test_without_since_hours_the_window_is_the_briefs_own(shadow):
    assert brief_replay.main(["--day", "2026-11-28"]) == 0
    assert shadow["since"] is None


def test_without_a_day_outside_the_morning_it_asks_for_one(shadow, monkeypatch, capsys):
    from app.kernel import brief
    monkeypatch.setattr(brief, "due_day", lambda now: None)
    assert brief_replay.main([]) == 2 and "--day" in capsys.readouterr().err and "day" not in shadow


def test_a_day_that_already_has_a_brief_is_refused(shadow, monkeypatch, capsys):
    from app import duty_brief
    monkeypatch.setattr(duty_brief, "get", lambda owner_hash, day: {"day": day, "outcome": "done"})
    assert brief_replay.main(["--day", "2026-11-28"]) == 2 and "--day" in capsys.readouterr().err and "day" not in shadow


def test_a_bad_day_is_an_argument_error():
    with pytest.raises(SystemExit):
        brief_replay.main(["--day", "11/28"])


def test_the_sample_ids_are_in_the_900_million_range_and_differ_per_run():
    first, second = brief_replay.sample_base(1_800_000_000), brief_replay.sample_base(1_800_000_001)
    assert 900_000_000 <= first < second and second + 3 < 1_000_000_000


def test_the_sample_is_the_four_kinds_of_overnight_row(owner):
    from app.kernel import brief, wake
    from app.database import SessionLocal
    with SessionLocal() as db:
        db.query(duty_log.DutyLog).delete()
        db.commit()
    start = datetime.now(UTC) - timedelta(minutes=1)
    rows = brief_replay.write_sample(OWNER_HASH, brief_replay.sample_base())
    assert [r["decision"] for r in rows] == ["digest", "tell_now", "record", "ignore"]
    assert all(900_000_000 <= r["alert_id"] < 1_000_000_000 and r["outcome"] == "decided" for r in rows)
    held = rows[1]
    assert held["delivery"] == wake.HELD_NIGHT and "原因" in held["message"] and held["event"]["deferred"] is True
    gathered = brief.gather(OWNER_HASH, start)
    assert gathered["counts"] == {"digest": 1, "held": 1, "record": 1, "ignore": 1, "told": 0, "failed": 0}
    assert gathered["held"][0]["id"] == held["id"] and gathered["kept"][0]["symbol"] == "AAPL"
