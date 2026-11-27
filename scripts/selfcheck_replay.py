"""Run the missed-alert check once on the shadow database and print its ``duty_selfcheck`` row (5c-3a).

  set -a; . /opt/finbot/ruler.env; set +a; export RULER_DATABASE_URL="$DATABASE_URL"
  python -m scripts.selfcheck_replay [--day 2026-11-28] [--now 2026-11-26T00:00:00+00:00] [--since-hours 400]

Run it from the code under test (the shadow's ``/opt/finbot/ruler-src`` with the branch synced in).  It refuses unless
``RULER_DATABASE_URL`` is set and equal to ``DATABASE_URL`` and the database is ``finbot_ruler`` (the guards of ``wake_replay``), and it
always runs in ``shadow`` mode.  The check writes nothing but its ``duty_selfcheck`` row; the sentinel database and the snapshot are read
only, by default the copies under this source tree's ``data/`` (``--sentinel-db`` / ``--snapshot`` name others).  ``--day`` names the
row's Beijing day and skips the 07:45–12:00 check (a day that already has a row is refused: pick another one); ``--now`` is the instant
the check is evaluated as (it decides the New York session the price check replays); ``--since-hours`` sets the window's start instead
of the last check that ran.  The price check fetches the bars from Yahoo, as ``sentinel_replay`` does."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.wake_replay import refusal  # noqa: E402  (the same shadow-database guards)

DEFAULT_SENTINEL_DB = ROOT / "data" / "sentinel.db"
DEFAULT_SNAPSHOT = ROOT / "data" / "sentinel-config.json"


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _instant(value: str) -> datetime:
    when = datetime.fromisoformat(value)
    if when.tzinfo is None:
        raise argparse.ArgumentTypeError("--now needs a time zone, e.g. 2026-11-26T00:00:00+00:00")
    return when.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", type=_day)
    ap.add_argument("--now", type=_instant)
    ap.add_argument("--since-hours", type=float)
    ap.add_argument("--sentinel-db", type=Path, default=DEFAULT_SENTINEL_DB)
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = ap.parse_args(argv)
    problem = refusal()
    if problem:
        print(problem, file=sys.stderr)
        return 2
    os.environ["FINBOT_DUTY_MODE"] = "shadow"          # never "off", whatever the environment file says
    from app import agent_task_runner as runner
    from app import duty_selfcheck
    from app.agent_chat_store import owner_hash
    from app.kernel import selfcheck
    credential = runner.owner_credential()
    if not credential:
        print("影子环境里没有 owner 凭证。", file=sys.stderr)
        return 2
    owner = owner_hash(credential)
    now = args.now or datetime.now(UTC)
    day = args.day or selfcheck.due_day(now)
    if day is None:
        print("现在不在北京时间 07:45–12:00 之间：请用 --day 指定自查的日期。", file=sys.stderr)
        return 2
    if duty_selfcheck.get(owner, day) is not None:
        print(f"{day} 已经有一次自查了：请用 --day 换一个日期。", file=sys.stderr)
        return 2
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    since = now - timedelta(hours=args.since_hours) if args.since_hours is not None else None
    row = selfcheck.run_once(owner, now, day=day, since=since, sentinel_db=args.sentinel_db, snapshot=snapshot)
    if row is None:
        print(f"{day} 的自查没有跑：这一天刚被别处占用。", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False, indent=1, default=str))
    return 0 if row.get("outcome") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
