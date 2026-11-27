"""Judge a past sentinel alert again with the wake turn, on the shadow database, and print what the kernel decided (5c-1).

  set -a; . /opt/finbot/ruler.env; set +a; export RULER_DATABASE_URL="$DATABASE_URL"
  python -m scripts.wake_replay --sentinel-db /opt/finbot/src/data/sentinel.db --alert 59 [--tier 2 --sigma 4.9] [--held]

Run it from the code under test (the shadow's ``/opt/finbot/ruler-src`` with the branch synced in).  It refuses unless
``RULER_DATABASE_URL`` is set and equal to ``DATABASE_URL`` (the shadow environment sourced as the README says), and it always runs
the wake in ``shadow`` mode, so nothing is sent whatever the environment says.  The sentinel database is opened read-only.  The
alert is judged under ``--id-offset`` + its id (default 900000000) so an alert already judged in the restored backup is judged
again instead of returning its old row.  ``--tier`` / ``--sigma`` set the 5a fields an alert from before 5a does not carry."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import urllib.parse
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OFFSET = 900_000_000
SHADOW_DB = "finbot_ruler"          # the shadow database's name: a replay on any other database is refused


def refusal(environ=os.environ) -> str | None:
    """Why this must not run here, or None."""
    shadow, current = environ.get("RULER_DATABASE_URL", ""), environ.get("DATABASE_URL", "")
    if not shadow:
        return "没有 RULER_DATABASE_URL：请先按 README 载入影子环境（. /opt/finbot/ruler.env），再导出 RULER_DATABASE_URL。"
    if shadow != current:
        return "DATABASE_URL 不是影子库：拒绝在别的库上回放。"
    if urllib.parse.urlparse(shadow).path.lstrip("/") != SHADOW_DB:
        return f"影子库应当叫 {SHADOW_DB}：拒绝在别的库上回放。"
    return None


def event_from(sentinel_db: str, alert_id: int, *, offset: int, tier: int | None, sigma: float | None, held: bool) -> dict:
    """The alert as an ``alert_posted`` event, from the sentinel's own row (read-only)."""
    connection = sqlite3.connect(f"file:{sentinel_db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        raise LookupError(f"哨兵库里没有提醒 #{alert_id}")
    event = {"alert_id": offset + alert_id, "symbol": row["symbol"], "kind": row["kind"], "text": row["text"],
             "created_at": row["created_at"], "deferred": bool(row["deferred"]), "escalate": bool(row["escalate"]),
             "held": held, "replay_of": alert_id}
    if tier is not None:
        event["tier"] = tier
    if sigma is not None:
        event["sigma_mult"] = sigma
    return event


def _tools_of(turn_id) -> list[str]:
    from sqlalchemy import select
    from app.agent_chat_models import AgentMessage
    from app.database import SessionLocal
    names: list[str] = []
    with SessionLocal() as db:
        for calls in db.scalars(select(AgentMessage.tool_calls).where(AgentMessage.turn_id == uuid.UUID(str(turn_id)), AgentMessage.role == "assistant")):
            names.extend(name for name in map(call_name, (calls or {}).get("calls") or []) if name)
    return names


def call_name(call) -> str | None:
    """A stored tool call's name (the protocol keeps it under ``function``)."""
    if not isinstance(call, dict):
        return None
    function = call.get("function")
    return (function.get("name") if isinstance(function, dict) else None) or call.get("name")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sentinel-db", required=True)
    ap.add_argument("--alert", type=int, required=True)
    ap.add_argument("--tier", type=int, choices=(0, 1, 2))
    ap.add_argument("--sigma", type=float)
    ap.add_argument("--held", action="store_true")
    ap.add_argument("--id-offset", type=int, default=DEFAULT_OFFSET)
    args = ap.parse_args(argv)
    problem = refusal()
    if problem:
        print(problem, file=sys.stderr)
        return 2
    os.environ["FINBOT_DUTY_MODE"] = "shadow"          # never sends, whatever the environment file says
    try:
        event = event_from(args.sentinel_db, args.alert, offset=args.id_offset, tier=args.tier, sigma=args.sigma, held=args.held)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    from app import agent_task_runner as runner
    from app.agent_chat_store import owner_hash
    from app.kernel import wake
    credential = runner.owner_credential()
    if not credential:
        print("影子环境里没有 owner 凭证。", file=sys.stderr)
        return 2
    row = asyncio.run(wake.wake(event, owner_hash=owner_hash(credential)))
    tools = _tools_of(row["turn_id"]) if row.get("turn_id") else []
    print(json.dumps({"alert": args.alert, "judged_as": event["alert_id"], "tier": event.get("tier"), "mode": row.get("mode"),
                      "outcome": row.get("outcome"), "decision": row.get("decision"), "ms": row.get("ms"),
                      "model_calls": row.get("model_calls"), "tools": tools, "reason": row.get("reason"),
                      "message": row.get("message")}, ensure_ascii=False, indent=1, default=str))
    return 0 if row.get("outcome") == "decided" else 1


if __name__ == "__main__":
    raise SystemExit(main())
