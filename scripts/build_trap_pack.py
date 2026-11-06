"""Build a code-constructed trap pack (U11).  Synthetic material only; the answer of every pair is known by construction.

Traps (expected: candidate):
  T1 subject swap   - a figure belongs to holder A in the source; the answer gives it to holder B (B's own figure differs)
  T2 period swap    - the source gives Q2 and Q3 opposite changes; the answer moves Q2's direction to Q3
  T3 derived claim  - the answer says a derived change (Q1->Q2 difference) was disclosed; the figure is absent
Controls (expected: no candidate):
  C1 alias          - the same holder under an alias that the material itself links (identity evidence in source)
  C2 period notation- 2026年第二季度 for 'Q2 2026' (P4: equivalent period, must never open a door)
  C3 honest calc    - the same derived change, stated as a calculation or estimate

Usage:
    python scripts/build_trap_pack.py --seed 7101 --out .local/trap-practice-r7.json --kind practice
The sealed pack is written by an independent executor (see the report); the designer does not open it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

NAMES = ["Harbor Ridge Capital", "Quill Peak Partners", "Northfield Trust", "Cobalt Bay Advisors",
         "Ember Grove Fund", "Silverline Holdings", "Marrow Creek Group", "Tallow Point Asset Management",
         "Juniper Vale Investors", "Sable Hill Capital", "Alder Cross Partners", "Brightwater Fund",
         "Copperleaf Capital", "Dunmore Bay Holdings", "Eastwold Investors", "Fernridge Group",
         "Galewood Partners", "Hollin Peak Capital", "Ironbark Trust", "Kestrel Row Advisors"]
ALIASES = {"Harbor Ridge Capital": "Harbor Ridge Cap.", "Quill Peak Partners": "Quill Peak Ptrs.",
           "Northfield Trust": "Northfield Tr.", "Cobalt Bay Advisors": "Cobalt Bay Adv."}
CLASSES = {"T1": "trap", "T2": "trap", "T3": "trap", "C1": "control", "C2": "control", "C3": "control"}
PER_CLASS = 20


def _shares(rng: random.Random) -> int:
    return rng.randrange(100_000, 40_000_000, 1_000)


def _pct(rng: random.Random) -> float:
    return round(rng.uniform(1.5, 45.0), 1)


def _source(text: str) -> list[dict]:
    return [{"ordinal": 1, "text": text, "source_type": "web", "complete": True}]


def _t1(rng, k):
    holders = rng.sample(NAMES, 4)
    a, b = holders[0], holders[1]
    n = _shares(rng)
    m = n
    while abs(m - n) / n < 0.05:
        m = _shares(rng)
    lines = [f"* [{a}] removed {n:,} shares (-{_pct(rng)}%) from their portfolio in Q2 2026",
             f"* [{b}] removed {m:,} shares (-{_pct(rng)}%) from their portfolio in Q2 2026",
             f"* [{holders[2]}] added {_shares(rng):,} shares (+{_pct(rng)}%) in Q2 2026"]
    rng.shuffle(lines)
    assert sum(f"{n:,}" in line for line in lines) == 1 and f"{n:,}" not in "".join(l for l in lines if b in l)
    sentence = f"{b} 在 2026 年第二季度减少约 {round(n / 10_000):,} 万股 [1]"
    return sentence, _source("\n".join(lines))


def _t2(rng, k):
    q2 = -_pct(rng)
    q3 = _pct(rng)
    text = f"| Period | Change % |\n|---|---|\n| Q2 2026 | {q2}% |\n| Q3 2026 | +{q3}% |"
    assert q2 < 0 < q3
    sentence = f"2026 年第三季度变动为下降约 {abs(q2)}% [1]"
    return sentence, _source(text)


def _t3(rng, k):
    name = NAMES[k % len(NAMES)]
    q1 = rng.randrange(500_000, 5_000_000, 1_000)
    delta = rng.randrange(50_000, 900_000, 1_000)
    q2 = q1 + delta
    text = f"* [{name}] held {q1:,} shares in Q1 2026\n* [{name}] held {q2:,} shares in Q2 2026"
    assert f"{delta:,}" not in text
    sentence = f"{name} 在 2026 年第二季度披露增持 {delta:,} 股 [1]"
    return sentence, _source(text)


def _c1(rng, k):
    name = list(ALIASES)[k % len(ALIASES)]
    shares = _shares(rng)
    text = f"* [{name} ({ALIASES[name]})] held {shares:,} shares in Q2 2026"
    sentence = f"{ALIASES[name]} 在 2026 年第二季度持有约 {round(shares / 10_000):,} 万股 [1]"
    return sentence, _source(text)


def _c2(rng, k):
    q2 = round(rng.uniform(1.5, 45.0), 1)
    text = f"| Period | Change % |\n|---|---|\n| Q2 2026 | −{q2}% |"
    sentence = f"2026年第二季度变动为下降约 {q2}% [1]"
    return sentence, _source(text)


def _c3(rng, k):
    name = NAMES[k % len(NAMES)]
    q1 = rng.randrange(500_000, 5_000_000, 1_000)
    delta = rng.randrange(50_000, 900_000, 1_000)
    text = f"* [{name}] held {q1:,} shares in Q1 2026\n* [{name}] held {q1 + delta:,} shares in Q2 2026"
    sentence = (f"按两期持仓计算，{name} 在 2026 年第二季度约增持 {delta:,} 股 [1]" if k % 2 == 0
                else f"{name} 在 2026 年第二季度增持的股数可由两期持仓差估算，约 {delta:,} 股 [1]")
    return sentence, _source(text)


BUILDERS = {"T1": _t1, "T2": _t2, "T3": _t3, "C1": _c1, "C2": _c2, "C3": _c3}
EXPECT = {"T1": "candidate", "T2": "candidate", "T3": "candidate", "C1": "no_candidate",
          "C2": "no_candidate", "C3": "no_candidate"}


def build(seed: int, kind: str) -> list[dict]:
    rng = random.Random(seed)
    items = []
    for cls in ("T1", "T2", "T3", "C1", "C2", "C3"):
        for k in range(PER_CLASS):
            sentence, sources = BUILDERS[cls](rng, k)
            items.append({"id": f"{kind}-{cls}-{k:02d}", "class": cls, "group": CLASSES[cls],
                          "expect": EXPECT[cls], "sentence": sentence, "sources": sources})
    return items


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--kind", choices=["practice", "sealed"], required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    items = build(args.seed, args.kind)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(items, ensure_ascii=False, indent=1).encode("utf-8")
    out.write_bytes(payload)
    if args.kind == "sealed":
        out.chmod(0o600)
    counts = {c: sum(1 for i in items if i["class"] == c) for c in CLASSES}
    print(json.dumps({"kind": args.kind, "items": len(items), "counts": counts,
                      "sha256": hashlib.sha256(payload).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
