"""Repair stored jin10-flash times that were read as UTC but are Beijing wall-clock.

Rows ingested before the fix have published_at 8 hours too late. This subtracts
8 hours from rows with time_inferred false and fetched_at before --cutoff (the
deploy time), so rows written by the fixed code are never touched, and a second
run changes nothing (changed ids are recorded and skipped).

Usage:
    PYTHONPATH=. .venv-rag/bin/python scripts/repair_jin10_times.py --cutoff 2026-11-25T03:00:00Z --dry-run
    PYTHONPATH=. .venv-rag/bin/python scripts/repair_jin10_times.py --cutoff 2026-11-25T03:00:00Z

The database comes from DATABASE_URL (never printed). Output files go to --out-dir
(default: ./jin10_repair_backups): a backup of (id, old published_at) before any
change, and a JSON list of changed ids next to it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

SOURCE_ID = "jin10-flash"
SHIFT = timedelta(hours=8)


def _parse_cutoff(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _changed_ids_files(out_dir: Path) -> list[Path]:
    return sorted(out_dir.glob("jin10_changed_ids_*.json"))


def run(database_url: str, cutoff: datetime, out_dir: Path, dry_run: bool) -> dict:
    engine = create_engine(database_url)
    out_dir.mkdir(parents=True, exist_ok=True)
    already: set[str] = set()
    for f in _changed_ids_files(out_dir):
        already.update(json.loads(f.read_text(encoding="utf-8")).get("ids", []))
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    "select id, published_at from news_items "
                    "where source_id = :sid and time_inferred = false and fetched_at < :cutoff "
                    "order by published_at"
                ),
                {"sid": SOURCE_ID, "cutoff": cutoff},
            ).all()
            rows = [(str(r[0]), r[1]) for r in rows if str(r[0]) not in already]
            result = {
                "affected": len(rows),
                "dry_run": dry_run,
                "sample": [
                    {"id": i, "old": p.isoformat(), "new": (p - SHIFT).isoformat()} for i, p in rows[:5]
                ],
                "backup_path": None,
                "changed_ids_path": None,
            }
            if dry_run or not rows:
                return result
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
            backup = out_dir / f"jin10_backup_{stamp}.json"
            changed = out_dir / f"jin10_changed_ids_{stamp}.json"
            backup.write_text(
                json.dumps([{"id": i, "published_at": p.isoformat()} for i, p in rows], ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"backup written: {backup}")
            for i, _ in rows:
                conn.execute(
                    text("update news_items set published_at = published_at - interval '8 hours' where id = :id"),
                    {"id": i},
                )
            changed.write_text(json.dumps({"cutoff": cutoff.isoformat(), "ids": [i for i, _ in rows]}), encoding="utf-8")
            result["backup_path"] = str(backup)
            result["changed_ids_path"] = str(changed)
            return result
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cutoff", required=True, help="deploy time (ISO 8601); only rows fetched before it are shifted")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-dir", default="jin10_repair_backups")
    args = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    res = run(url, _parse_cutoff(args.cutoff), Path(args.out_dir), args.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
