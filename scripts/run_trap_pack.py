"""Run a trap pack (scripts/build_trap_pack.py) through the judge and the short review (U11).

Uses the same path as the 185 replay (judge_claims -> review_candidate / review_attribution).
Reports, per class: candidate detection (contradiction or attribution candidate), door opens,
attribution review passes, and false door opens on controls.  Practice results are not acceptance results.

Usage (key from an env file, proxy only for this script):
    MODEL_EGRESS_PROXY="$HTTPS_PROXY" python scripts/run_trap_pack.py --pack .local/trap-practice-r7.json \
        --model deepseek-flash --provider deepseek --base-url https://api.deepseek.com \
        --key-env DEEPSEEK_API_KEY --env-file ~/workspace/projects/FinBot/.env --out .local/trap-practice-r7-run.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.agent_workflow.claim_judge import JudgeSource  # noqa: E402
from claim_replay_185 import judge_item  # noqa: E402


def load_items(pack_path: Path) -> list[dict]:
    items = []
    for it in json.loads(pack_path.read_text(encoding="utf-8")):
        sources = [JudgeSource(s["ordinal"], s["text"], s.get("source_type"), bool(s.get("complete")))
                   for s in it["sources"]]
        items.append({"turn": it["id"][:12], "idx": 0, "text": it["sentence"], "sources": sources,
                      "gold": "problem" if it["class"].startswith("T") else "clean",
                      "gold_raw": it["class"], "class": it["class"], "id": it["id"]})
    return items


def summarize(rows: list[dict]) -> dict:
    per = {}
    for row in rows:
        stat = per.setdefault(row["class"], Counter())
        stat["n"] += 1
        stat["provider_or_timeout"] += row["status"] != "ok"
        detected = row["status"] == "ok" and (row["verdict"] == "contradiction" or row["attribution_candidates"] > 0)
        stat["candidate"] += detected
        stat["door_open"] += bool(row["door_open"])
        stat["attribution_reviews_passed"] += sum(bool(a["passed"]) for a in row.get("attribution_reviews", []))
    return {cls: dict(stat) for cls, stat in sorted(per.items())}


async def main_async(args) -> None:
    if args.env_file:
        from dotenv import dotenv_values
        key = dotenv_values(args.env_file).get(args.key_env) or ""
    else:
        key = os.environ.get(args.key_env) or ""
    if not key:
        raise SystemExit(f"missing key in {args.key_env}")
    model = {"provider": args.provider, "model": args.model, "api_key": key, "base_url": args.base_url}
    items = load_items(Path(args.pack))
    sem = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(*(judge_item(it, model, sem, args.timeout) for it in items))
    for it, row in zip(items, rows):
        row["class"] = it["class"]
        row["id"] = it["id"]
    summary = summarize(rows)
    Path(args.out).write_text(json.dumps({"model": args.model, "provider": args.provider, "summary": summary,
                                          "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pack", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--base-url", default=None)
    p.add_argument("--key-env", required=True)
    p.add_argument("--env-file", default=None)
    p.add_argument("--out", required=True)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--timeout", type=float, default=45.0)
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
