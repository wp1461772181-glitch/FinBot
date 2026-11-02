"""SQLite retry queue for events that could not reach the API (stdlib only)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "sentinel.db"


def db_path() -> Path:
    return Path(os.environ.get("SENTINEL_DB_PATH") or DEFAULT_DB)


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS event_queue ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, payload TEXT NOT NULL,"
                "created_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute("CREATE TABLE IF NOT EXISTS baseline (symbol TEXT PRIMARY KEY, data TEXT NOT NULL,"
                         "baseline_at REAL NOT NULL, splits_at REAL NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS signal_cooldown (symbol TEXT NOT NULL, key TEXT NOT NULL,"
                         "ts REAL NOT NULL, mult REAL NOT NULL, PRIMARY KEY (symbol, key))")
            conn.execute("CREATE TABLE IF NOT EXISTS price_state (symbol TEXT PRIMARY KEY, price REAL NOT NULL, ts REAL NOT NULL)")

    def _conn(self) -> sqlite3.Connection:
        # One short-lived connection per call: safe across the sentinel's threads.
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # the Telegram bridge writes acknowledgements to this file too
        return conn

    def enqueue(self, event_type: str, payload: dict) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO event_queue (type, payload, created_at) VALUES (?, ?, ?)",
                (event_type, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            return int(cur.lastrowid)

    def pending(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM event_queue ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "type": r["type"], "payload": json.loads(r["payload"]), "attempts": r["attempts"]} for r in rows]

    def delete(self, event_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM event_queue WHERE id = ?", (event_id,))

    def bump(self, event_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE event_queue SET attempts = attempts + 1 WHERE id = ?", (event_id,))

    def count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM event_queue").fetchone()[0])

    # --- intraday signals (Task 11) ---------------------------------------------------------------
    def get_baseline(self, symbol: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM baseline WHERE symbol = ?", (symbol,)).fetchone()
        if row is None:
            return None
        return {"data": json.loads(row["data"]), "baseline_at": row["baseline_at"], "splits_at": row["splits_at"]}

    def set_baseline(self, symbol: str, data: dict, baseline_at: float, splits_at: float) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO baseline (symbol, data, baseline_at, splits_at) VALUES (?, ?, ?, ?)",
                         (symbol, json.dumps(data), baseline_at, splits_at))

    def get_cooldown(self, symbol: str, key: str) -> tuple[float, float] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT ts, mult FROM signal_cooldown WHERE symbol = ? AND key = ?", (symbol, key)).fetchone()
        return None if row is None else (row["ts"], row["mult"])

    def set_cooldown(self, symbol: str, key: str, ts: float, mult: float) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO signal_cooldown (symbol, key, ts, mult) VALUES (?, ?, ?, ?)",
                         (symbol, key, ts, mult))

    def get_price(self, symbol: str) -> float | None:
        with self._conn() as conn:
            row = conn.execute("SELECT price FROM price_state WHERE symbol = ?", (symbol,)).fetchone()
        return None if row is None else row["price"]

    def set_price(self, symbol: str, price: float) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO price_state (symbol, price, ts) VALUES (?, ?, ?)", (symbol, price, time.time()))

    def earnings_alert_unacked(self, symbol: str) -> bool:
        """Is there an earnings alert for ``symbol`` nobody has acknowledged?  Reads the ``alerts`` table that
        the escalation code (Task 12) creates and the earnings monitor (Task 9) will fill; without that table
        or without such a row it is simply False."""
        try:
            with self._conn() as conn:
                row = conn.execute("SELECT 1 FROM alerts WHERE symbol = ? AND kind = 'earnings' AND acked_at IS NULL LIMIT 1",
                                   (symbol,)).fetchone()
        except sqlite3.OperationalError:
            return False
        return row is not None
