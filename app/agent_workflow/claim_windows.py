"""Mechanical numeric locations for claim review. No attribution is inferred here."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from .claim_judge import JudgeSource
from .evidence import _figure_records, _match

WINDOW_VERSION = "numeric-window-v1"
_NUMBER = re.compile(
    r'(?<![A-Za-z0-9_.])(?P<sign>[-−+＋]?)(?P<currency>[$¥￥€£]?)'
    r'(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
    r'[ \t]*(?P<scale>万亿|千万|百万|万|亿|千|trillion|billion|million|thousand|bn|mn|[bkm])?'
    r'[ \t]*(?P<unit>%|％|股|shares?|USD|CNY|元)?(?![A-Za-z0-9_.])', re.I)


@dataclass(frozen=True)
class Figure:
    text: str
    start: int
    end: int
    value: float
    digits: int
    scaled: bool
    unit: str


def figures(text: str) -> list[Figure]:
    """Parse supported digit forms, keeping original offsets; unsupported forms are omitted."""
    found = []
    for m in _NUMBER.finditer(text):
        token = m.group(0).strip()
        records = _figure_records(token)
        if len(records) != 1:
            continue
        record = records[0]
        sign = -1 if m.group('sign') in ('-', '−') else 1
        unit = (m.group('unit') or '').lower()
        if unit == '％':
            unit = '%'
        elif unit in ('股', 'share', 'shares'):
            unit = 'shares'
        currency = m.group('currency')
        if currency:
            unit = currency
        start = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
        end = m.end() - (len(m.group(0)) - len(m.group(0).rstrip()))
        found.append(Figure(text[start:end], start, end, sign * record['value'],
                            record['digits'], record['scaled'], unit))
    return found


def _block(text: str, start: int, end: int) -> tuple[int, int, list[tuple[int, int]]]:
    """Keep each source block intact; table header is a separate original span."""
    line_start = text.rfind('\n', 0, start) + 1
    line_end = text.find('\n', end)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    headers = []
    if line.lstrip().startswith('|'):
        previous_end = line_start - 1
        previous_start = text.rfind('\n', 0, previous_end) + 1
        previous = text[previous_start:previous_end]
        if re.fullmatch(r'\s*\|?[\s:|\-]+\|?\s*', previous) and '-' in previous:
            header_end = previous_start - 1
            header_start = text.rfind('\n', 0, header_end) + 1
            if text[header_start:header_end].lstrip().startswith('|'):
                headers.append((header_start, header_end))
    elif not re.match(r'\s*(?:[-*+]\s+|\d+[.)]\s+)', line):
        # Paragraphs are delimited by blank lines; do not join independent list items.
        prior = text.rfind('\n\n', 0, start)
        after = text.find('\n\n', end)
        candidate_start, candidate_end = prior + 2 if prior >= 0 else 0, after if after >= 0 else len(text)
        paragraph = text[candidate_start:candidate_end]
        if not re.search(r'(?m)^\s*(?:\||[-*+]\s+|\d+[.)]\s+)', paragraph):
            line_start, line_end = candidate_start, candidate_end
    return line_start, line_end, headers


def numeric_windows(sentence: str, sources: Sequence[JudgeSource], *, max_windows: int = 24,
                    max_chars: int = 16000) -> dict:
    """Return literal spans and exact/rounded location facts, never a negative finding."""
    anchors = figures(re.sub(r'\[\d+\]', lambda m: ' ' * len(m.group()), sentence))
    windows = []
    omitted = 0
    used = 0
    for source in sources:
        for source_figure in figures(source.text):
            for anchor in anchors:
                if anchor.unit and source_figure.unit and anchor.unit != source_figure.unit:
                    continue
                if (anchor.unit == '%') != (source_figure.unit == '%'):
                    continue
                if (anchor.value < 0) != (source_figure.value < 0):
                    continue
                record = {'value': abs(anchor.value), 'digits': anchor.digits, 'scaled': anchor.scaled}
                match = _match(record, {abs(source_figure.value)}, set(), False, False)
                if match not in ('exact', 'rounded'):
                    continue
                start, end, headers = _block(source.text, source_figure.start, source_figure.end)
                size = end - start + sum(b-a for a, b in headers)
                if len(windows) >= max_windows or used + size > max_chars:
                    omitted += 1
                    continue
                used += size
                windows.append({'ordinal': source.ordinal, 'answer_span': [anchor.start, anchor.end],
                                'source_number_span': [source_figure.start, source_figure.end],
                                'source_span': [start, end], 'text': source.text[start:end],
                                'headers': [{'span': [a, b], 'text': source.text[a:b]} for a, b in headers],
                                'match': match})
    return {'version': WINDOW_VERSION, 'windows': windows, 'omitted': omitted}
