"""5a T2: the day state and the level locks survive in sqlite; old tables keep their meaning."""
import sqlite3

from sentinel.store import Store


def test_tier_state_is_per_symbol_date_and_direction(tmp_path):
    s = Store(tmp_path / "s.db")
    assert s.get_tier_states("INTC", "2026-11-03") == {}
    s.set_tier_state("INTC", "2026-11-03", "down", max_tier=1, extreme_r=-0.1, last_push_ts=5.0)
    s.set_tier_state("INTC", "2026-11-03", "down", max_tier=2)                 # a later write merges fields
    s.set_tier_state("INTC", "2026-11-03", "up", extreme_r=0.02)
    s.set_tier_state("INTC", "2026-11-04", "down", max_tier=1)
    got = s.get_tier_states("INTC", "2026-11-03")
    assert set(got) == {"up", "down"}
    assert (got["down"]["max_tier"], got["down"]["extreme_r"], got["down"]["last_push_ts"]) == (2, -0.1, 5.0)
    assert got["up"]["max_tier"] == 0 and got["up"]["reversal_said"] == 0
    assert s.get_tier_states("INTC", "2026-11-05") == {} and s.get_tier_states("AMD", "2026-11-03") == {}


def test_tier_state_survives_a_restart(tmp_path):
    Store(tmp_path / "s.db").set_tier_state("INTC", "2999-01-03", "down", max_tier=1, reversal_said=1)   # a future date: not pruned
    again = Store(tmp_path / "s.db")
    assert again.get_tier_states("INTC", "2999-01-03")["down"]["reversal_said"] == 1


def test_level_lock_roundtrip_keyed_by_the_level_price(tmp_path):
    s = Store(tmp_path / "s.db")
    assert s.get_level("INTC", "plan_add", 55.0) is None
    s.set_level("INTC", "plan_add", 55.0, {"armed": 0, "last_date": "2026-11-03", "count_today": 2})
    assert s.get_level("INTC", "plan_add", 55.0) == {"armed": 0, "last_date": "2026-11-03", "count_today": 2}
    assert s.get_level("INTC", "plan_add", 54.0) is None and s.get_level("INTC", "plan_stop", 55.0) is None


def test_old_dates_are_dropped_on_start_but_a_fresh_state_is_kept(tmp_path):
    s = Store(tmp_path / "s.db")
    s.set_tier_state("INTC", "2020-01-02", "down", max_tier=1)
    s.set_tier_state("INTC", "2999-01-02", "down", max_tier=1)
    s = Store(tmp_path / "s.db")
    assert s.get_tier_states("INTC", "2020-01-02") == {} and s.get_tier_states("INTC", "2999-01-02")


def test_existing_tables_are_untouched(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE price_event (symbol TEXT NOT NULL, ny_date TEXT NOT NULL, first_ts REAL NOT NULL,"
                 "first_bucket TEXT NOT NULL, anchor_price REAL NOT NULL, anchor_r REAL NOT NULL, anchor_ts REAL NOT NULL,"
                 "last_push_ts REAL NOT NULL, step REAL NOT NULL, open_checked INTEGER NOT NULL DEFAULT 0,"
                 "pushes INTEGER NOT NULL DEFAULT 0, suppressed INTEGER NOT NULL DEFAULT 0, low REAL, high REAL,"
                 "last_price REAL, last_r REAL, pending_alert_id INTEGER, PRIMARY KEY (symbol, ny_date))")
    conn.commit()
    conn.close()
    s = Store(path)
    s.set_tier_state("INTC", "2999-01-02", "up", max_tier=1)
    assert s.get_event("INTC", "2999-01-02") is None
