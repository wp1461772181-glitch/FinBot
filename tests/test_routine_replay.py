"""``scripts.routine_replay`` refuses to run outside the shadow environment (it makes, runs and deletes a task)."""
import asyncio

from scripts import routine_replay


def test_it_refuses_without_the_shadow_environment(monkeypatch, capsys):
    monkeypatch.delenv("RULER_DATABASE_URL", raising=False)
    called = []
    monkeypatch.setattr("app.agent_task_runner.run_brief", lambda *a, **k: called.append(a))
    assert asyncio.run(routine_replay.main(["--instruction", "x"])) == 2
    assert "RULER_DATABASE_URL" in capsys.readouterr().err and called == []


def test_it_refuses_a_database_that_is_not_the_shadow(monkeypatch, capsys):
    monkeypatch.setenv("RULER_DATABASE_URL", "postgresql://u@h/finbot")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h/finbot")
    assert asyncio.run(routine_replay.main(["--instruction", "x"])) == 2
    assert "finbot_ruler" in capsys.readouterr().err
