"""Write the morning brief once on the shadow database and print its ``duty_brief`` row (5c-2).

  set -a; . /opt/finbot/ruler.env; set +a; export RULER_DATABASE_URL="$DATABASE_URL"
  python -m scripts.brief_replay [--write-sample] [--day 2026-11-28] [--since-hours 24]

Run it from the code under test (the shadow's ``/opt/finbot/ruler-src`` with the branch synced in).  It refuses unless
``RULER_DATABASE_URL`` is set and equal to ``DATABASE_URL`` and the database is ``finbot_ruler`` (the guards of ``wake_replay``), and it
always runs in ``shadow`` mode, so nothing is sent whatever the environment says.  ``--write-sample`` first writes four ``duty_log``
rows (a digest, a night-held follow-up with a cause, a record, an ignore) under alert ids from ``SAMPLE_OFFSET``.  ``--day`` names the
brief's day and skips the 08:05–12:00 check (a day that already has a brief is refused: pick another one); ``--since-hours`` sets the
window's start instead of the last brief that ran."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.wake_replay import refusal  # noqa: E402  (the same shadow-database guards)

SAMPLE_OFFSET = 990_000_000        # sample alert ids: 990000000 + a per-run stamp, apart from wake_replay's 900000000 + alert id
SAMPLE_TEXT = {
    "digest": ("AAPL", "【盘中异动】AAPL 较昨收跌 3.2%，现价 221.4", "不急，他没有重仓 AAPL；早上一并说一下就够。"),
    "held": ("NVDA", "【夜间异动】NVDA 盘后跌 6.1%，现价 120.0", "夜里压住的提醒，原因已查到，早上告诉他。"),
    "record": ("MSFT", "【盘中异动】MSFT 较昨收涨 1.1%", "例行波动，记下即可。"),
    "ignore": ("TSLA", "【盘中异动】TSLA 较昨收涨 0.8%", "他不关心这只，不用打扰。"),
}
SAMPLE_MESSAGE = ("NVDA 盘后跌 6.1%。原因：路透 11-27 报道美国拟进一步收紧对华高端芯片出口，公司尚未回应。"
                  "你的仓位里 NVDA 占两成，开盘前可以看一下这条新闻的后续。")


def sample_base(now: float | None = None) -> int:
    """The first alert id of this run's sample rows (a stamp per run, so a second run writes new rows)."""
    return SAMPLE_OFFSET + (int(now if now is not None else time.time()) % 1_000_000) * 10


def write_sample(owner_hash: str, base: int) -> list[dict]:
    """Four duty rows as the wake would leave them overnight; returns them."""
    from app import duty_log
    from app.kernel import wake
    rows = []
    for offset, (kind, decision) in enumerate((("digest", "digest"), ("held", "tell_now"), ("record", "record"), ("ignore", "ignore"))):
        symbol, text, reason = SAMPLE_TEXT[kind]
        held = kind == "held"
        rows.append(duty_log.record(owner_hash, base + offset, event={"alert_id": base + offset, "symbol": symbol, "kind": "sample", "text": text,
                                                                      "deferred": held, "sample": True},
                                    mode="shadow", outcome="decided", decision=decision, reason=reason,
                                    message=SAMPLE_MESSAGE if held else None, delivery=wake.HELD_NIGHT if held else None))
    return rows


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write-sample", action="store_true")
    ap.add_argument("--day", type=_day)
    ap.add_argument("--since-hours", type=float)
    args = ap.parse_args(argv)
    problem = refusal()
    if problem:
        print(problem, file=sys.stderr)
        return 2
    os.environ["FINBOT_DUTY_MODE"] = "shadow"          # never sends, whatever the environment file says
    from app import agent_task_runner as runner
    from app import duty_brief
    from app.agent_chat_store import owner_hash
    from app.kernel import brief
    credential = runner.owner_credential()
    if not credential:
        print("影子环境里没有 owner 凭证。", file=sys.stderr)
        return 2
    owner = owner_hash(credential)
    now = datetime.now(UTC)
    day = args.day or brief.due_day(now)
    if day is None:
        print("现在不在北京时间 08:05–12:00 之间：请用 --day 指定简报的日期。", file=sys.stderr)
        return 2
    if duty_brief.get(owner, day) is not None:
        print(f"{day} 已经有一份简报了：请用 --day 换一个日期。", file=sys.stderr)
        return 2
    sample = write_sample(owner, sample_base()) if args.write_sample else []
    since = now - timedelta(hours=args.since_hours) if args.since_hours is not None else None
    row = asyncio.run(brief.run_once(owner, now, day=day, since=since))
    if row is None:
        print(f"{day} 的简报没有写：这一天刚被别处占用。", file=sys.stderr)
        return 1
    print(json.dumps({"sample_alert_ids": [r.get("alert_id") for r in sample], **row}, ensure_ascii=False, indent=1, default=str))
    return 0 if row.get("outcome") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
