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
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.wake_replay import refusal  # noqa: E402  (the same shadow-only guard)

DEFAULT_LIMIT = 200


_PLANT = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{3,}(?:\.\d+)?|\d+\.\d+)(?=\s*(?:%|亿|万|美元|百万|\[))")


def plant(answer: str) -> tuple[str, str | None]:
    """The answer with its first money / percent / cited figure replaced by that figure × 1.37 (a figure no source states), and the
    planted token; (answer, None) when it has none.  Only for measuring how much the check still catches."""
    match = _PLANT.search(answer or "")
    if not match:
        return answer, None
    value = float(match.group(1).replace(",", "")) * 1.37
    token = f"{value:,.2f}" if "." in match.group(1) else f"{round(value):,}"
    return answer[:match.start(1)] + token + answer[match.end(1):], token


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
    ap.add_argument("--plant", action="store_true",
                    help="also plant one figure from nowhere in each answer (its first sourced figure × 1.37) and say how many are caught")
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
    planted: list[dict] = []
    with SessionLocal() as db:
        for row in reconcile.kernel_answers(db, args.limit):
            inputs = reconcile.inputs_of(db, row)
            results.append((str(row.id), reconcile.reconcile(inputs["answer"], inputs["citations"], question=inputs["question"],
                                                             user_text=inputs["user_text"], earlier=inputs["earlier"])))
            if args.plant:
                planted_answer, token = plant(inputs["answer"])
                if token:
                    found = reconcile.reconcile(planted_answer, inputs["citations"], question=inputs["question"],
                                                user_text=inputs["user_text"], earlier=inputs["earlier"])
                    planted.append({"message_id": str(row.id), "planted": token,
                                    "caught": any(token in v for f in found.get("flagged") or [] for v in f["values"])})
        db.rollback()          # read only: nothing this session did is kept
    out = summary(results)
    if args.plant:
        out["planted"] = {"answers": len(planted), "caught": sum(p["caught"] for p in planted), "missed": [p for p in planted if not p["caught"]]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
