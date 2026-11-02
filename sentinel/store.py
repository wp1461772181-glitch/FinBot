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

    def _conn(self) -> sqlite3.Connection:
        # One short-lived connection per call: safe across the sentinel's threads.
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
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
