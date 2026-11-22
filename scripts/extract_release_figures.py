"""Read earnings-press-release figures into the 8-K rows that query_financials can serve.

``python scripts/extract_release_figures.py [--symbol NVDA]`` lists the releases that would be read and writes nothing.
``--apply`` runs the same pass as the background loop (one model call per release, the owner's 财报判断模型) and stores the
checked figures on each 8-K row.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import release_figures  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="", help="only this ticker")
    parser.add_argument("--apply", action="store_true", help="call the model and write the figures (default: list only)")
    args = parser.parse_args()
    symbol = args.symbol.strip() or None
    candidates = release_figures.find_candidates(symbol)
    for item in candidates:
        print(f"{item['symbol']}\t{item['accession_number']}\t{item['filed_at']}")
    print(f"{len(candidates)} candidate release(s)")
    if not args.apply:
        print("dry run: nothing read or written; add --apply to extract")
        return 0
    print(release_figures.run_once(symbol=symbol))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
