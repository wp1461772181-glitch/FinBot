"""5a T4: the replay harness on built bars (no network) and its comparison with a built alerts table."""
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sentinel import replay
from sentinel.store import Store

ET = ZoneInfo("America/New_York")


def et(day, hour, minute):
    return datetime(2026, 11, day, hour, minute, tzinfo=ET).astimezone(UTC)


def session(day, price_at):
    """5-minute bars 04:00-19:55 ET; ``price_at(hour, minute)`` gives the close."""
    out, ts = [], et(day, 4, 0)
    while ts < et(day, 20, 0):
        local = ts.astimezone(ET)
        out.append({"ts": ts, "close": price_at(local.hour, local.minute), "volume": 1000})
        ts += timedelta(minutes=5)
    return out


def drop(hour, minute):
    return 40.0 if (hour, minute) < (10, 0) else 33.6        # -16% from 10:00


def flat(hour, minute):
    return 100.0


def data():
    daily = lambda close: [{"ts": et(2, 14, 30), "close": close, "volume": 1}]   # noqa: E731
    return {"bars5": {"INTC": session(3, drop), "SPY": session(3, flat)}, "daily": {"INTC": daily(40.0), "SPY": daily(100.0)},
            "errors": {}}


SNAP = {"positions": [{"symbol": "INTC", "shares": 100}], "research_queue": [], "total_assets": 1_000_000.0}


def test_tiers_replay_sends_one_push_for_the_day(tmp_path):
    result = replay.run_replay(data(), SNAP, date(2026, 11, 3), date(2026, 11, 3), policy="tiers", workdir=tmp_path)
    assert [a["symbol"] for a in result["alerts"]] == ["INTC"]
    first = result["alerts"][0]
    assert first["tier"] == 2 and "同期标普 +0.0%" in first["text"]
    c = replay.counts(result)
    assert c["total"] == 1 and c["per_symbol"] == {"INTC": 1} and c["per_tier"] == {"2": 1}


def test_the_same_bars_under_the_anchor_policy(tmp_path):
    result = replay.run_replay(data(), SNAP, date(2026, 11, 3), date(2026, 11, 3), policy="anchor", workdir=tmp_path)
    assert result["alerts"] and result["alerts"][0]["tier"] == ""
    assert replay.counts(result)["per_tier"] == {"-": len(result["alerts"])}


def test_replay_is_reproducible(tmp_path):
    a = replay.run_replay(data(), SNAP, date(2026, 11, 3), date(2026, 11, 3), workdir=tmp_path / "a")
    b = replay.run_replay(data(), SNAP, date(2026, 11, 3), date(2026, 11, 3), workdir=tmp_path / "b")
    assert [(x["ts"], x["text"]) for x in a["alerts"]] == [(x["ts"], x["text"]) for x in b["alerts"]]


def test_days_without_bars_are_skipped(tmp_path):
    result = replay.run_replay(data(), SNAP, date(2026, 11, 7), date(2026, 11, 8), workdir=tmp_path)    # a weekend
    assert result["alerts"] == []


def test_compare_actual_lines_up_each_actual_alert(tmp_path):
    result = replay.run_replay(data(), SNAP, date(2026, 11, 3), date(2026, 11, 3), workdir=tmp_path / "r")
    new_ts = result["alerts"][0]["ts"]
    live = Store(tmp_path / "live.db")
    live.add_alert("INTC", "daily", "【盘中异动】INTC 较昨收跌 16.0%", True, new_ts + 120)          # two minutes later: matched
    live.add_alert("INTC", "update", "【异动更新】INTC 又跌", True, et(3, 15, 0).timestamp())      # hours later: not matched
    live.add_alert("INTC", "earnings", "财报", True, new_ts)                                      # not a price alert
    rows = replay.compare_actual(tmp_path / "live.db", result, date(2026, 11, 3), date(2026, 11, 3))
    assert [r["would_send"] for r in rows] == [True, False] and rows[0]["new_tier"] == 2
    assert "同一方向已经提醒过" in rows[1]["why_not"]
    out = tmp_path / "out"
    out.mkdir()
    replay.write_alerts_csv(result, out / "alerts.csv")
    replay.write_summary(result, out / "summary.md", title="t", args_line="x", notes=["n"], comparison=rows)
    assert "INTC" in (out / "alerts.csv").read_text(encoding="utf-8")
    assert "新规则也会发 1 条" in (out / "summary.md").read_text(encoding="utf-8")


def test_cache_roundtrip(tmp_path):
    path = tmp_path / "bars.json"
    replay.dump_data(data(), path)
    again = replay.load_data(path)
    assert again["bars5"]["INTC"][0]["ts"] == data()["bars5"]["INTC"][0]["ts"] and json.loads(path.read_text())["errors"] == {}


def test_cli_runs_offline_from_a_cache_and_writes_the_report(tmp_path, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("sentinel_replay_cli", Path(__file__).resolve().parent.parent / "scripts" / "sentinel_replay.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    cache, snap, out = tmp_path / "bars.json", tmp_path / "snap.json", tmp_path / "out"
    replay.dump_data(data(), cache)
    snap.write_text(json.dumps(SNAP), encoding="utf-8")
    code = cli.main(["--symbols", "INTC", "--snapshot", str(snap), "--from", "2026-11-03", "--to", "2026-11-03",
                     "--cache", str(cache), "--out", str(out)])
    assert code == 0 and json.loads(capsys.readouterr().out)["total"] == 1
    assert (out / "alerts-tiers.csv").exists() and (out / "summary-tiers.md").exists()
