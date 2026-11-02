#!/usr/bin/env python3
"""Verify that the database connection keeps session-level advisory locks.

A transaction pooler (Supabase port 6543) breaks pg_try_advisory_lock because
consecutive statements can land on different server sessions. Run this against
the real DATABASE_URL before any cutover; it exits non-zero on failure.

  connection A takes the lock  -> connection B cannot get it
  connection A closes          -> connection B gets it
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import DATABASE_URL  # noqa: E402

LOCK_KEY = 7_420_113_377  # arbitrary, not used by the application


def _try_lock(conn) -> bool:
    return bool(conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())


def main() -> int:
    engine = create_engine(DATABASE_URL, pool_size=2, max_overflow=0, connect_args={"connect_timeout": 10})
    ok = True
    try:
        a = engine.connect()
        b = engine.connect()
        a_got = _try_lock(a)
        print(f"A try_lock: {a_got} (expect True)")
        ok &= a_got
        b_got = _try_lock(b)
        print(f"B try_lock while A holds: {b_got} (expect False)")
        ok &= not b_got
        # Same session must also see the lock persist across statements (pooler check).
        pid_1 = a.execute(text("select pg_backend_pid()")).scalar()
        pid_2 = a.execute(text("select pg_backend_pid()")).scalar()
        print(f"A backend pid stable across statements: {pid_1 == pid_2}")
        ok &= pid_1 == pid_2
        # Closing (not returning to pool) the raw connection ends the server session.
        a.invalidate()
        a.close()
        got = False
        for _ in range(20):
            got = _try_lock(b)
            if got:
                break
            time.sleep(0.5)
        print(f"B try_lock after A disconnects: {got} (expect True)")
        ok &= got
        if got:
            b.execute(text("select pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
        b.close()
    finally:
        engine.dispose()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
