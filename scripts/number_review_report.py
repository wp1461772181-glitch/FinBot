"""Read-only report of the number review ledger (数字二审, ``num-v1``) for the owner to read by hand.

Lists every line the review took off the unverified list (hint) with its sentence, the quotes it rests on and the
source numbers, then a sample of the lines it left flagged (kept), so a misread can be seen next to a missed one.
Lines that kept some figures (partial) are counted.  Writes nothing.

    python scripts/number_review_report.py [--dir DIR] [--sample 20] [--seed 0]

DIR defaults to $CLAIM_JUDGE_SHADOW_DIR or /opt/finbot/judge-shadow; the ledger is DIR/numbers/*.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

DEFAULT_DIR = "/opt/finbot/judge-shadow"


def load_entries(ledger: Path) -> tuple[list[dict], list[dict], int]:
    """(entry rows, call rows, unreadable lines) from every ledger file, in file order."""
    entries: list[dict] = []
    calls: list[dict] = []
    broken = 0
    if not ledger.is_dir():
        return entries, calls, broken
    for name in sorted(os.listdir(ledger)):
        if not name.endswith(".jsonl"):
            continue
        with open(ledger / name, encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    broken += 1
                    continue
                if not isinstance(row, dict) or row.get("channel") != "numbers":
                    continue
                if row.get("kind") == "entry":
                    entries.append(row)
                elif row.get("kind") == "call":
                    calls.append(row)
    return entries, calls, broken


def _evidence_text(row: dict) -> list[str]:
    out = []
    for result in row.get("results") or []:
        if result.get("status") == "found":
            out.append(f"  来源 [{result.get('quote_ordinal')}] 写作「{result.get('quote')}」，读作 {result.get('read_as')}")
        elif result.get("status") == "derived":
            operands = "、".join(f"[{o.get('ordinal')}]「{o.get('quote')}」" for o in result.get("operands") or [])
            out.append(f"  由 {operands} 推算：{result.get('method')}")
        elif result.get("status") == "conflict":
            out.append(f"  来源 [{result.get('quote_ordinal')}] 写作「{result.get('quote')}」（与这句不一致）")
        else:
            out.append(f"  {result.get('figure')}：未采纳（{result.get('reason')}）")
    return out


def _sentence(row: dict) -> list[str]:
    return [
        f"- turn {row.get('turn_id')} · 闸原因 {row.get('gate_reason')} · 数字 {', '.join(row.get('numbers') or [])}",
        f"  原句：{row.get('line')}",
        *_evidence_text(row),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", default=os.environ.get("CLAIM_JUDGE_SHADOW_DIR") or DEFAULT_DIR)
    parser.add_argument("--sample", type=int, default=20, help="kept lines to sample (default 20)")
    parser.add_argument("--seed", type=int, default=0, help="sample seed (default 0)")
    args = parser.parse_args(argv)

    ledger = Path(args.dir) / "numbers"
    entries, calls, broken = load_entries(ledger)
    sent = [row for row in entries if row.get("sent", True)]
    hints = [row for row in sent if row.get("after") == "hint"]
    partial = [row for row in sent if row.get("after") == "partial"]
    kept = [row for row in sent if row.get("after") == "kept"]
    over_cap = [row for row in entries if not row.get("sent", True)]
    statuses: dict[str, int] = {}
    for call in calls:
        statuses[str(call.get("status"))] = statuses.get(str(call.get("status")), 0) + 1

    print(f"数字二审账本：{ledger}")
    print(f"调用 {len(calls)} 次（{', '.join(f'{k} {v}' for k, v in sorted(statuses.items())) or '无'}）；"
          f"送审行 {len(sent)}；降为提示 {len(hints)}；部分摘出 {len(partial)}；保留 {len(kept)}；"
          f"超出每轮上限未送审 {len(over_cap)}；无法解析的行 {broken}")
    print()
    print(f"== 降为提示（全部 {len(hints)} 条）：读它们是否真在说这个量 ==")
    for row in hints:
        print("\n".join(_sentence(row)))
        print()
    print(f"== 保留的抽样（{min(args.sample, len(kept))} / {len(kept)} 条，seed={args.seed}）：读它们来源里是否其实有 ==")
    rng = random.Random(args.seed)
    for row in rng.sample(kept, min(args.sample, len(kept))):
        print("\n".join(_sentence(row)))
        print(f"  去向：保留（{row.get('kept_reason')}）")
        print()
    if partial:
        print(f"== 部分摘出（{len(partial)} 条，未在报告中逐条列出；需要时在账本里按 after=partial 查）==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
