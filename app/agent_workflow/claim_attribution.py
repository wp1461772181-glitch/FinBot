"""Conservative literal-number presence, used only to nominate shadow attribution checks."""
from __future__ import annotations

import re
from .claim_judge import JudgeSource
from .claim_windows import figures
from .evidence import _match

# Unsupported numeric representations make absence unprovable; these are parser-coverage checks,
# not semantic classification of the answer.
_UNPARSED = re.compile(r'[零〇一二两三四五六七八九十百千万亿点]|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|half|quarter|percent|basis points?)\b|\d\s*/\s*\d|\d[eE][+-]?\d', re.I)


def number_presence(token: str, sources: list[JudgeSource], *, truncated: bool = False) -> str:
    target = figures(token)
    if len(target) != 1 or not sources or truncated:
        return 'unknown'
    target = target[0]
    # Magnitude only: a sentence often states direction in words ('下降约 19.2%') while the source writes '−19.2%'.
    # A sign difference is a direction question for the judge, never a reason to call the number absent.
    for source in sources:
        for item in figures(source.text):
            record = {'value': abs(target.value), 'digits': target.digits, 'scaled': target.scaled}
            if _match(record, {abs(item.value)}, set(), False, False) in {'exact', 'rounded'}:
                return 'present'
    if any(not source.complete or _UNPARSED.search(source.text) for source in sources):
        return 'unknown'
    return 'absent'
