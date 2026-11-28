"""List what the owner said he was not told (``app.missed_reports``), newest first: the raw material for new watch rules and ruler questions.

  python -m scripts.missed_reports [--limit 50] [--json]

Read only.  Run where the database the environment names is the one to read (on the box: the API's environment)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    from app import missed_reports
    from app.sentinel_bridge import owner_hash_from_login_config
    owner = owner_hash_from_login_config()
    if not owner:
        print("没有 owner 登录配置。", file=sys.stderr)
        return 2
    rows = missed_reports.recent(owner, args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    elif not rows:
        print("还没有记下过「这事怎么没告诉我」。")
    else:
        for row in rows:
            print(f"{row['created_local']}  {row['symbol'] or '-':6}  {row['what']}" + (f"  （原话：{row['quote']}）" if row.get("quote") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
