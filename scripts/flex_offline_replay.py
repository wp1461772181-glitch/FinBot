"""Offline gate for the flex number review (numeric mode): 185 corpus or trap pack.

Reads the same frozen inputs as scripts/claim_replay_185.py and scripts/run_trap_pack.py, runs each sentence
through ``flex_number_review.review_offline`` (positions -> model responsibility/relation/operands -> code
verification -> one targeted retry), and writes per-row records.  Prints only the summary.

What is measured per row (no door is opened here):
  candidate  = at least one numeric position with a finding (arithmetic_difference / numeric_difference /
               same_quantity_difference).  Unverified or incomplete positions are never candidates.
The frozen judge result (old pipeline, unchanged) is read from --frozen and printed beside it.  The flex
mode is NOT connected to the short review or the public gate, so its "actual door" is not measured here.

Usage:
    python scripts/flex_offline_replay.py --suite 185 --out .local/flex-185.json \
        --frozen ~/workspace/projects/FinBot/.worktrees/unified-plan/.local/replay185-glm-adjacent.json
    python scripts/flex_offline_replay.py --suite trap --pack ~/workspace/goals/finbot/hidden_files/trap-sealed-r7.json \
        --out .local/flex-trap.json --frozen ~/workspace/projects/FinBot/.worktrees/unified-plan/.local/trap-sealed-glm-run.json

The API key is read from --key-env (env or --env-file) and is never written to the output.
Model calls must go through the operator egress proxy, as in scripts/run_trap_pack.py:
    MODEL_EGRESS_PROXY="$HTTPS_PROXY" python scripts/flex_offline_replay.py ...
Without it the direct pinned transport did not return in this environment (probe timed out at 60-90 s).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.agent_workflow.flex_number_review import VERSION, review_offline  # noqa: E402
from claim_replay_185 import HIDDEN, adjacent_contexts, load_items  # noqa: E402
from run_trap_pack import load_items as load_trap_items  # noqa: E402

FINDING_REASONS = {"arithmetic_difference", "numeric_difference", "same_quantity_difference"}


def is_candidate(result: dict) -> bool:
    return any(r.get("status") == "finding" for r in result["results"]) or bool(result["findings"])


def record(key: dict, gold: str, result: dict | None, error: str | None) -> dict:
    if result is None:
        return {**key, "gold": gold, "status": "error", "error": error, "candidate": False, "positions": []}
    positions = [{k: r.get(k) for k in ("id", "figure", "responsibility", "relation", "kind", "status", "reason",
                                        "computed_value", "steps")} for r in result["results"]]
    return {**key, "gold": gold, "status": "ok", "candidate": is_candidate(result),
            "findings": result["findings"], "pending_ids": result["pending_ids"], "positions": positions}


async def run_all(jobs, model, timeout, concurrency):
    sem = asyncio.Semaphore(concurrency)

    async def one(job):
        async with sem:
            try:
                result = await review_offline(job["text"], job["sources"], model, context=job["context"],
                                              timeout=timeout)
                return record(job["key"], job["gold"], result, None)
            except Exception as exc:  # noqa: BLE001 - a replay row never aborts the run
                return record(job["key"], job["gold"], None, type(exc).__name__)

    rows = []
    started = time.time()
    for done, fut in enumerate(asyncio.as_completed([one(j) for j in jobs]), 1):
        rows.append(await fut)
        if done % 25 == 0:
            print(f"{done}/{len(jobs)} ({time.time() - started:.0f}s)", file=sys.stderr, flush=True)
    return rows


def frozen_index(path: Path | None, key_fn) -> dict:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key_fn(r): r for r in data["rows"]}


def summarize_185(rows: list[dict], frozen: dict) -> dict:
    out = {"suite": "185", "total": len(rows), "status": dict(Counter(r["status"] for r in rows))}
    for gold in ("problem", "clean", "unverifiable"):
        group = [r for r in rows if r["gold"] == gold]
        old = [frozen.get((r["turn"], r["idx"])) for r in group]
        out[gold] = {
            "n": len(group),
            "flex_candidate": sum(r["candidate"] for r in group),
            "flex_incomplete_positions": sum(1 for r in group for p in r["positions"] if p["status"] == "incomplete"),
            "flex_errors": sum(r["status"] != "ok" for r in group),
            "old_judge_not_supported": sum(1 for o in old if o and o.get("status") == "ok" and o.get("verdict") != "supported"),
            "old_door_open": sum(1 for o in old if o and o.get("door_open")),
            "flex_door_open": "not_wired",
        }
    out["flex_candidate_reasons"] = dict(Counter(f["reason"] for r in rows for f in r["findings"]))
    out["flex_candidate_problem_list"] = [f"{r['turn']}#{r['idx']}" for r in rows if r["gold"] == "problem" and r["candidate"]]
    out["flex_candidate_clean_list"] = [f"{r['turn']}#{r['idx']}" for r in rows if r["gold"] == "clean" and r["candidate"]]
    return out


def summarize_trap(rows: list[dict], frozen: dict) -> dict:
    per: dict[str, Counter] = {}
    for r in rows:
        stat = per.setdefault(r["class"], Counter())
        stat["n"] += 1
        stat["error"] += r["status"] != "ok"
        stat["flex_candidate"] += r["candidate"]
        old = frozen.get(r["id"])
        stat["old_candidate"] += bool(old and old.get("status") == "ok" and (
            old.get("verdict") == "contradiction" or old.get("attribution_candidates", 0) > 0))
        stat["old_door_open"] += bool(old and old.get("door_open"))
    return {cls: {**dict(stat), "flex_door_open": "not_wired"} for cls, stat in sorted(per.items())}


async def main_async(args) -> None:
    if args.env_file:
        from dotenv import dotenv_values
        key = dotenv_values(args.env_file).get(args.key_env) or ""
    else:
        key = os.environ.get(args.key_env) or ""
    if not key:
        raise SystemExit(f"missing key in {args.key_env}")
    model = {"provider": args.provider, "model": args.model, "api_key": key, "base_url": args.base_url}
    if args.suite == "185":
        items = load_items(HIDDEN / "corpus185.json", HIDDEN / "gold-final.json")
        contexts = adjacent_contexts(items) if args.context == "adjacent" else {}
        jobs = [{"key": {"turn": it["turn"], "idx": it["idx"]}, "gold": it["gold"], "text": it["text"],
                 "sources": {str(s.ordinal): s.text for s in it["sources"]},
                 "context": contexts.get((it["turn"], it["idx"]), "")} for it in items]
        frozen = frozen_index(Path(args.frozen).expanduser() if args.frozen else None,
                              lambda r: (r["turn"], r["idx"]))
        rows = await run_all(jobs, model, args.timeout, args.concurrency)
        rows.sort(key=lambda r: (r["turn"], r["idx"]))
        summary = summarize_185(rows, frozen)
    else:
        items = load_trap_items(Path(args.pack).expanduser())
        jobs = [{"key": {"class": it["class"], "id": it["id"]}, "gold": it["gold"], "text": it["text"],
                 "sources": {str(s.ordinal): s.text for s in it["sources"]}, "context": ""} for it in items]
        frozen = frozen_index(Path(args.frozen).expanduser() if args.frozen else None, lambda r: r["id"])
        rows = await run_all(jobs, model, args.timeout, args.concurrency)
        for r, it in zip(rows, items):
            r["class"] = it["class"]
            r["id"] = it["id"]
        summary = summarize_trap(rows, frozen)
    Path(args.out).write_text(json.dumps({"review_version": VERSION, "model": args.model, "provider": args.provider,
                                          "suite": args.suite, "summary": summary, "rows": rows},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--suite", choices=["185", "trap"], required=True)
    p.add_argument("--pack", default=None, help="trap pack JSON (suite trap)")
    p.add_argument("--frozen", default=None, help="frozen judge run for side-by-side columns")
    p.add_argument("--model", default="z-ai/glm-5.3-flash")
    p.add_argument("--provider", default="openrouter")
    p.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    p.add_argument("--key-env", default="OPENROUTER_API_KEY")
    p.add_argument("--env-file", default=None)
    p.add_argument("--out", required=True)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--timeout", type=float, default=40.0)
    p.add_argument("--context", choices=["adjacent", "none"], default="adjacent")
    args = p.parse_args()
    if args.suite == "trap" and not args.pack:
        p.error("--pack is required for suite trap")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
