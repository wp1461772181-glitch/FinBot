"""Measure the false alarms of the 5d-1 figure check on stored kernel answers, on the shadow database, before it ships.

  set -a; . /opt/finbot/ruler.env; set +a; export RULER_DATABASE_URL="$DATABASE_URL"
  python -m scripts.reconcile_report [--limit 200]

It refuses unless ``RULER_DATABASE_URL`` is set, equals ``DATABASE_URL`` and names ``finbot_ruler`` (the guard of
``scripts/wake_replay.py``).  It reads the newest ``--limit`` kernel answers (assistant rows whose protocol route is ``K``), runs
``app.kernel.reconcile.reconcile`` on each with the inputs the background job reads (``reconcile.inputs_of``), and prints the flag rate
and every flagged line with its answer id.  It writes nothing: not the result, not anything else."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.wake_replay import refusal  # noqa: E402  (the same shadow-only guard)

DEFAULT_LIMIT = 200


def summary(results: list[tuple[str, dict]]) -> dict:
    """The report of ``(message_id, result)`` pairs: how many answers, how many were checked, flagged and failed, the flag rate over the
    checked ones, and every flagged line and every failure with its answer id."""
    checked = [(mid, result) for mid, result in results if "error" not in result]
    flagged = [{"message_id": mid, "line": item["line"], "values": item["values"]} for mid, result in checked for item in result.get("flagged") or []]
    flagged_answers = len({item["message_id"] for item in flagged})
    return {"answers": len(results), "checked": len(checked), "flagged_answers": flagged_answers,
            "flag_rate": round(flagged_answers / len(checked), 4) if checked else None,
            "figures": sum(result.get("figures") or 0 for _, result in checked), "flagged_lines": len(flagged),
            "errors": [{"message_id": mid, "error": result["error"]} for mid, result in results if "error" in result],
            "flagged": flagged}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = ap.parse_args(argv)
    if args.limit < 1:
        print("--limit 至少是 1。", file=sys.stderr)
        return 2
    problem = refusal()
    if problem:
        print(problem, file=sys.stderr)
        return 2
    from app.database import SessionLocal
    from app.kernel import reconcile
    results = []
    with SessionLocal() as db:
        for row in reconcile.kernel_answers(db, args.limit):
            inputs = reconcile.inputs_of(db, row)
            results.append((str(row.id), reconcile.reconcile(inputs["answer"], inputs["citations"], question=inputs["question"],
                                                             user_text=inputs["user_text"])))
        db.rollback()          # read only: nothing this session did is kept
    print(json.dumps(summary(results), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
