"""Sentinel core: stdlib-only, isolated loops, snapshot reload, memory-gated worker start."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from sentinel import main as sentinel_main
from sentinel import signals
from sentinel.signals import SnapshotConfig
from sentinel.store import Store

ROOT = Path(__file__).resolve().parent.parent


def test_sentinel_does_not_import_app():
    code = "import sys, sentinel.main; sys.exit(1 if any(m == 'app' or m.startswith('app.') for m in sys.modules) else 0)"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_snapshot_reload_on_mtime(tmp_path):
    path = tmp_path / "sentinel-config.json"
    path.write_text(json.dumps({"research_queue": ["AAPL"]}))
    config = SnapshotConfig(path)
    assert config.get()["research_queue"] == ["AAPL"]
    path.write_text(json.dumps({"research_queue": ["MSFT"]}))
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 5_000_000_000))
    assert config.get()["research_queue"] == ["MSFT"]
    path.unlink()  # API down / file gone: the last snapshot is kept
    assert config.get()["research_queue"] == ["MSFT"]


def _sentinel(tmp_path):
    return sentinel_main.Sentinel(SnapshotConfig(tmp_path / "none.json"), Store(tmp_path / "s.db"))


def test_worker_not_started_when_memory_low(tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(signals, "pending_forecast_jobs", lambda base: 2)
    monkeypatch.setattr(signals, "worker_running", lambda: False)
    monkeypatch.setattr(signals, "spawn_worker", lambda: spawned.append(1))
    monkeypatch.setattr(signals, "mem_available_mb", lambda: 199.0)
    s = _sentinel(tmp_path)
    s.check_forecast_jobs()
    assert spawned == []
    monkeypatch.setattr(signals, "mem_available_mb", lambda: 200.0)
    s.check_forecast_jobs()
    assert spawned == [1]


def test_mem_available_parses_meminfo(tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemTotal: 8000000 kB\nMemAvailable:  204800 kB\n")
    assert signals.mem_available_mb(str(f)) == 200.0


def test_one_loop_failure_does_not_stop_others(tmp_path):
    s = _sentinel(tmp_path)
    ticks = threading.Event()
    count = {"bad": 0, "good": 0}

    def bad():
        count["bad"] += 1
        raise RuntimeError("boom")

    def good():
        count["good"] += 1
        if count["good"] >= 3:
            ticks.set()

    s.jobs = lambda: {"bad": bad, "good": good}
    threads = s.start(interval=0.01)
    assert ticks.wait(5)
    s.stop.set()
    for t in threads:
        t.join(2)
    assert count["bad"] >= 2  # the failing loop itself keeps retrying


def test_events_queue_when_api_down_and_resend(tmp_path, monkeypatch):
    s = _sentinel(tmp_path)
    sent = []

    def down(base, t, p):
        raise OSError("down")

    monkeypatch.setattr(signals, "post_event", down)
    s.post_event("alert_posted", {"id": 1})
    assert s.store.count() == 1
    s.resend_events()
    assert s.store.count() == 1
    monkeypatch.setattr(signals, "post_event", lambda b, t, p: sent.append((t, p)))
    s.resend_events()
    assert s.store.count() == 0 and sent == [("alert_posted", {"id": 1})]


def test_three_failures_notify_once(tmp_path, monkeypatch):
    from sentinel import notify
    messages = []
    monkeypatch.setattr(signals, "probe_health", lambda base: False)
    monkeypatch.setattr(notify, "notify", lambda snap, text: messages.append(text) or True)
    s = _sentinel(tmp_path)
    for _ in range(5):
        s.check_health()
    assert len(messages) == 1 and s.health_failures == 5
