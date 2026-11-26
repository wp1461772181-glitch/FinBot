"""Replay the sentinel's price-alert policy over real 5-minute bars (stage 5a).

  python -m scripts.sentinel_replay --symbols INTC,AAPL,NVDA --snapshot snapshot.json --from 2026-11-03 --to 2026-11-25 \
      [--policy tiers|anchor] [--sensitivity standard] [--short-moves] [--out DIR] [--cache bars.json] \
      [--compare-actual COPY_OF_sentinel.db]

Fetches from Yahoo (the sentinel's own fetchers) unless ``--cache`` names an existing file, in which case it reads that;
a new ``--cache`` path is written after fetching so a second run (another policy) sees the same bars.  The snapshot JSON has the
shape of data/sentinel-config.json: ``positions``, ``plans``, ``total_assets``, ``research_queue``.  Nothing is sent."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    from sentinel import replay
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--snapshot", default=str(ROOT / "data" / "sentinel-config.json"))
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--policy", choices=("tiers", "anchor"), default="tiers")
    ap.add_argument("--sensitivity", default="standard")
    ap.add_argument("--short-moves", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--cache", default="")
    ap.add_argument("--compare-actual", default="")
    args = ap.parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cache = Path(args.cache) if args.cache else None
    if cache and cache.exists():
        data = replay.load_data(cache)
    else:
        data = replay.fetch_data(sorted(set(symbols) | {"SPY"}))
        if cache:
            replay.dump_data(data, cache)
    for symbol, error in data["errors"].items():
        print(f"fetch failed for {symbol}: {error}", file=sys.stderr)
    result = replay.run_replay(data, snapshot, start, end, policy=args.policy, sensitivity=args.sensitivity,
                               short_moves=args.short_moves)
    comparison = replay.compare_actual(args.compare_actual, result, start, end) if args.compare_actual else None
    c = replay.counts(result)
    print(json.dumps(c, ensure_ascii=False, indent=1))
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        replay.write_alerts_csv(result, out / f"alerts-{args.policy}.csv")
        notes = [f"持仓和计划取自 {Path(args.snapshot).name}（回放用的快照，不是当时的真实快照）",
                 "回放没有套用夜间规则（北京时间 0 点到 8 点），实际会进简报的提醒也列在里面"]
        notes += [f"{s} 没取到数据：{e}" for s, e in data["errors"].items()]
        replay.write_summary(result, out / f"summary-{args.policy}.md", title=f"哨兵回放（{args.policy}，{args.sensitivity}）",
                             args_line="python -m scripts.sentinel_replay " + " ".join(argv if argv is not None else sys.argv[1:]),
                             notes=notes, comparison=comparison)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
