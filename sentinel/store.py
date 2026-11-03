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
            conn.execute("CREATE TABLE IF NOT EXISTS alerts ("
                         "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,"
                         "escalate INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, acked_at REAL,"
                         "tg_chat_id INTEGER, tg_message_id INTEGER, last_sent_at REAL, resends INTEGER NOT NULL DEFAULT 0,"
                         "deferred INTEGER NOT NULL DEFAULT 0, digested_at REAL,"
                         "receipt TEXT, receipt_closed INTEGER NOT NULL DEFAULT 0, escalated_at REAL)")
            conn.execute("CREATE TABLE IF NOT EXISTS earnings_seen ("
                         "accession TEXT PRIMARY KEY, symbol TEXT NOT NULL, cik TEXT NOT NULL, held INTEGER NOT NULL,"
                         "filed TEXT NOT NULL, accepted_at REAL NOT NULL, primary_doc TEXT, url TEXT,"
                         "detected_at REAL NOT NULL, seeded INTEGER NOT NULL DEFAULT 0, delivered_at REAL, fallback_at REAL)")
            conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, ts REAL NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS price_state (symbol TEXT PRIMARY KEY, price REAL NOT NULL, ts REAL NOT NULL)")
            # One push event per symbol per New York date (design-alert-policy.md section 1 and 7).
            conn.execute("CREATE TABLE IF NOT EXISTS price_event ("
                         "symbol TEXT NOT NULL, ny_date TEXT NOT NULL, first_ts REAL NOT NULL, first_bucket TEXT NOT NULL,"
                         "anchor_price REAL NOT NULL, anchor_r REAL NOT NULL, anchor_ts REAL NOT NULL,"
                         "last_push_ts REAL NOT NULL, step REAL NOT NULL, open_checked INTEGER NOT NULL DEFAULT 0,"
                         "pushes INTEGER NOT NULL DEFAULT 0, suppressed INTEGER NOT NULL DEFAULT 0,"
                         "low REAL, high REAL, last_price REAL, last_r REAL, pending_alert_id INTEGER,"
                         "PRIMARY KEY (symbol, ny_date))")
            # CREATE TABLE IF NOT EXISTS never adds columns to a table an older release made.
            have = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)")}
            for column, ddl in (("superseded_by", "INTEGER"), ("event_date", "TEXT"), ("digest_text", "TEXT")):
                if column not in have:
                    conn.execute(f"ALTER TABLE alerts ADD COLUMN {column} {ddl}")
            conn.execute("DELETE FROM price_event WHERE first_ts < ?", (time.time() - 7 * 86400,))

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

    def earnings_alert_unacked(self, symbol: str, within: float = 24 * 3600) -> bool:
        """Is there an earnings alert for ``symbol`` from the last ``within`` seconds nobody has acknowledged?
        Reads the ``alerts`` table that the escalation code (Task 12) creates and the earnings monitor (Task 9)
        will fill; without that table or without such a row it is simply False.  Bounded, so one forgotten
        earnings row cannot make every later fall on the symbol ring for ever."""
        try:
            with self._conn() as conn:
                row = conn.execute("SELECT 1 FROM alerts WHERE symbol = ? AND kind = 'earnings' AND acked_at IS NULL"
                                   " AND created_at >= ? LIMIT 1", (symbol, time.time() - within)).fetchone()
        except sqlite3.OperationalError:
            return False
        return row is not None

    # --- price events (the push policy) ---------------------------------------------------------------
    def get_event(self, symbol: str, ny_date: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM price_event WHERE symbol = ? AND ny_date = ?", (symbol, ny_date)).fetchone()
        return None if row is None else dict(row)

    def latest_event_before(self, symbol: str, ny_date: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM price_event WHERE symbol = ? AND ny_date < ? ORDER BY ny_date DESC LIMIT 1",
                               (symbol, ny_date)).fetchone()
        return None if row is None else dict(row)

    def open_event(self, symbol: str, ny_date: str, *, first_ts: float, first_bucket: str, price: float, r: float,
                   step: float, pending_alert_id: int | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO price_event (symbol, ny_date, first_ts, first_bucket, anchor_price, anchor_r, anchor_ts,"
                " last_push_ts, step, pushes, low, high, last_price, last_r, pending_alert_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (symbol, ny_date, first_ts, first_bucket, price, r, first_ts, first_ts, step, price, price, price, r,
                 pending_alert_id))

    def update_event(self, symbol: str, ny_date: str, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{name} = ?" for name in fields)
        with self._conn() as conn:
            conn.execute(f"UPDATE price_event SET {sets} WHERE symbol = ? AND ny_date = ?", (*fields.values(), symbol, ny_date))

    def delete_event(self, symbol: str, ny_date: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM price_event WHERE symbol = ? AND ny_date = ?", (symbol, ny_date))

    def track_event(self, symbol: str, ny_date: str, price: float, r: float, *, suppressed: bool = False) -> None:
        """Every poll of an open event: the latest price, the extremes since the anchor, and the held-back counter."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE price_event SET last_price = ?, last_r = ?, low = MIN(COALESCE(low, ?), ?), high = MAX(COALESCE(high, ?), ?),"
                " suppressed = suppressed + ? WHERE symbol = ? AND ny_date = ?",
                (price, r, price, price, price, price, 1 if suppressed else 0, symbol, ny_date))

    def rebase_event(self, symbol: str, ny_date: str, now: float) -> None:
        """A night digest delivered the event's line: the anchor becomes the price the digest showed."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE price_event SET anchor_price = COALESCE(last_price, anchor_price), anchor_r = COALESCE(last_r, anchor_r),"
                " anchor_ts = ?, low = last_price, high = last_price, pending_alert_id = NULL WHERE symbol = ? AND ny_date = ?",
                (now, symbol, ny_date))

    def recent_price_push_symbols(self, since: float) -> set[str]:
        """Symbols that got an individual price push since ``since`` (merged messages are not individual)."""
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT symbol FROM alerts WHERE kind IN ('short', 'daily', 'gap', 'update')"
                                " AND deferred = 0 AND created_at >= ?", (since,)).fetchall()
        return {r["symbol"] for r in rows}

    def recent_earnings(self, symbol: str, since: float) -> list[dict]:
        """Earnings filings seen for ``symbol`` since ``since`` (seeded history rows do not count)."""
        return self.earnings_rows("symbol = ? AND seeded = 0 AND detected_at >= ?", (symbol, since))

    # --- alerts and acknowledgements (Task 12) -----------------------------------------------------
    # The Telegram bridge writes ``acked_at`` here (button press or a reply to the alert message), the
    # sentinel's escalation reads it.  WAL (set per connection above) lets both processes use the file.
    def add_alert(self, symbol: str, kind: str, text: str, escalate: bool, created_at: float, *, deferred: bool = False,
                  event_date: str | None = None, digest_text: str | None = None) -> int:
        with self._conn() as conn:
            cur = conn.execute("INSERT INTO alerts (symbol, kind, text, escalate, created_at, deferred, event_date, digest_text)"
                               " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (symbol, kind, text, int(escalate), created_at, int(deferred), event_date, digest_text))
            return int(cur.lastrowid)

    def alert(self, alert_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return None if row is None else dict(row)

    def update_alert(self, alert_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{name} = ?" for name in fields)
        with self._conn() as conn:
            conn.execute(f"UPDATE alerts SET {sets} WHERE id = ?", (*fields.values(), alert_id))

    def alerts_where(self, where: str, params: tuple = ()) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(f"SELECT * FROM alerts WHERE {where} ORDER BY id", params).fetchall()]

    def ack_alert(self, alert_id: int, now: float | None = None) -> bool:
        """True when this call is the one that acknowledged it."""
        with self._conn() as conn:
            stamp = now or time.time()
            cur = conn.execute("UPDATE alerts SET acked_at = ? WHERE id = ? AND acked_at IS NULL", (stamp, alert_id))
            # a merged message replaced its members' live alerts: acknowledging it acknowledges them too
            conn.execute("UPDATE alerts SET acked_at = ? WHERE superseded_by = ? AND acked_at IS NULL", (stamp, alert_id))
            return cur.rowcount > 0

    def ack_by_message(self, chat_id: int, message_id: int, now: float | None = None) -> int | None:
        """A reply to the alert message counts as an acknowledgement; returns the alert id, None if no alert matches."""
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM alerts WHERE tg_message_id = ? AND (tg_chat_id = ? OR tg_chat_id IS NULL)",
                               (message_id, chat_id)).fetchone()
        if row is None:
            return None
        self.ack_alert(row["id"], now)
        return int(row["id"])

    # --- earnings filings (Task 9) ------------------------------------------------------------------
    def add_earnings(self, row: dict) -> bool:
        """True when this accession is new (the primary key makes a repeat, or a restart, a no-op)."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO earnings_seen (accession, symbol, cik, held, filed, accepted_at, primary_doc, url, detected_at, seeded)"
                " VALUES (:accession, :symbol, :cik, :held, :filed, :accepted_at, :primary_doc, :url, :detected_at, :seeded)", row)
            return cur.rowcount > 0

    def earnings_rows(self, where: str = "1=1", params: tuple = ()) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(f"SELECT * FROM earnings_seen WHERE {where} ORDER BY accepted_at", params).fetchall()]

    def update_earnings(self, accession: str, **fields) -> None:
        sets = ", ".join(f"{name} = ?" for name in fields)
        with self._conn() as conn:
            conn.execute(f"UPDATE earnings_seen SET {sets} WHERE accession = ?", (*fields.values(), accession))

    def last_earnings_date(self, symbol: str):
        from datetime import date
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(filed) FROM earnings_seen WHERE symbol = ?", (symbol,)).fetchone()
        return date.fromisoformat(row[0]) if row and row[0] else None

    def get_kv(self, key: str):
        with self._conn() as conn:
            row = conn.execute("SELECT value, ts FROM kv WHERE key = ?", (key,)).fetchone()
        return None if row is None else (json.loads(row["value"]), row["ts"])

    def set_kv(self, key: str, value) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO kv (key, value, ts) VALUES (?, ?, ?)", (key, json.dumps(value), time.time()))
