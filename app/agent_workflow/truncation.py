"""Truncation governance: a machine consumer never sees silently cut text.

Presentation may truncate.  A checker or a model that reasons over a text must get all of it, or be
told the cut.  Where a budget is unavoidable it cuts at *item* boundaries (a whole source, a whole
line, a whole status), never inside one, and every such cut is recorded in the turn audit as
``truncation_events: [{site, original_chars, kept_chars, ...}]``.
"""
from __future__ import annotations

import json

MAX_EVENTS = 40


def record(audit: dict, site: str, original_chars: int, kept_chars: int, **extra) -> dict | None:
    """Note one machine-path cut in ``audit['truncation_events']``.

    A turn builds the same model payload several times; one event per site is kept and updated, with
    ``count`` saying how many times the site cut."""
    if kept_chars >= original_chars:
        return None
    events = audit.setdefault('truncation_events', [])
    for event in events:
        if event['site'] == site:
            event.update(original_chars=original_chars, kept_chars=kept_chars, count=event.get('count', 1) + 1, **extra)
            return event
    if len(events) >= MAX_EVENTS:
        return None
    event = {'site': site, 'original_chars': original_chars, 'kept_chars': kept_chars, **extra, 'count': 1}
    events.append(event)
    return event


def size_of(item) -> int:
    return len(json.dumps(item, ensure_ascii=False, default=str))


def select_whole_items(items: list, budget: int, size=size_of) -> tuple[list, list, int, int]:
    """Whole items, newest first, until the budget is spent.

    ``items`` are in chronological order; the newest has priority and the kept ones come back in the
    same order.  The newest item is always kept, so a single large source is not turned into nothing.
    Returns ``(kept, dropped, original_chars, kept_chars)``."""
    sizes = [size(item) for item in items]
    keep: list[int] = []
    used = 0
    for index in range(len(items) - 1, -1, -1):
        if keep and used + sizes[index] > budget:
            break
        keep.append(index)
        used += sizes[index]
    keep.sort()
    kept = [items[i] for i in keep]
    dropped = [item for i, item in enumerate(items) if i not in set(keep)]
    return kept, dropped, sum(sizes), used


def _rows(observation):
    result = observation.get('result') if isinstance(observation, dict) else None
    data = result.get('data') if isinstance(result, dict) else None
    return data if isinstance(data, list) else None


def fit_observations(observations: list[dict], budget: int, max_observations: int = 10):
    """The accepted-evidence payload for a model: whole sources (rows) until the budget is spent.

    The newest observations have priority, a row is never cut, and an observation that loses rows says
    how many (``omitted_rows``).  Returns ``(kept, omitted_labels, original_chars, kept_chars)`` where
    ``omitted_labels`` names each dropped source (its citation marker when it has one)."""
    original = size_of(observations)
    old = observations[:-max_observations] if len(observations) > max_observations else []
    recent = observations[len(old):]
    if not old and original <= budget:
        return observations, [], original, original
    units = []                                        # (observation, row, size): newest first, rows in order
    shells = {}
    for oi in range(len(recent) - 1, -1, -1):
        data = _rows(recent[oi])
        if data is None:
            units.append((oi, None, size_of(recent[oi])))
            continue
        shells[oi] = size_of({**recent[oi], 'result': {**recent[oi]['result'], 'data': []}})
        units.extend((oi, ri, size_of(row)) for ri, row in enumerate(data))
    chosen = set()
    opened = set()
    used = 0
    for oi, ri, cost in units:
        extra = cost + (shells[oi] if ri is not None and oi not in opened else 0)
        if chosen and used + extra > budget:
            break
        chosen.add((oi, ri))
        used += extra
        if ri is not None:
            opened.add(oi)
    kept, omitted = [], [o.get('name') for o in old if isinstance(o, dict)]
    for oi, observation in enumerate(recent):
        data = _rows(observation)
        if data is None:
            if (oi, None) in chosen:
                kept.append(observation)
            else:
                omitted.append(observation.get('name') if isinstance(observation, dict) else None)
            continue
        keep = [row for ri, row in enumerate(data) if (oi, ri) in chosen]
        gone = [row for ri, row in enumerate(data) if (oi, ri) not in chosen]
        omitted.extend((row.get('citation') if isinstance(row, dict) else None) or observation.get('name') for row in gone)
        if keep:
            kept.append({**observation, 'result': {**observation['result'], 'data': keep,
                                                   **({'omitted_rows': len(gone)} if gone else {})}})
    return kept, omitted, original, size_of(kept)


def compact_tool_content(content: str, budget: int) -> str:
    """A tool result (JSON text) that must fit ``budget``: whole rows from the front, the rest counted.

    The result says it was cut (``truncated``, ``omitted_items``), so the model narrows its query
    instead of reasoning over half a row.  Text that is not a list of rows is replaced by a marker."""
    try:
        value = json.loads(content)
    except ValueError:
        value = None
    data = value.get('data') if isinstance(value, dict) else None
    if isinstance(data, list):
        kept = list(data)
        while True:
            text = json.dumps({**value, 'data': kept, 'truncated': True, 'omitted_items': len(data) - len(kept)},
                              ensure_ascii=False, default=str)
            if len(text) <= budget or not kept:
                return text
            kept.pop()
    return json.dumps({'ok': value.get('ok') if isinstance(value, dict) else None, 'truncated': True,
                       'omitted_chars': len(content), 'note': 'result too large to show; narrow the request'},
                      ensure_ascii=False)


def cut_lines(text: str, budget: int) -> tuple[str, int, int, int]:
    """Whole lines from the start of ``text`` within the budget (the first line is always kept).
    Returns ``(kept_text, original_chars, kept_chars, dropped_lines)``."""
    if len(text) <= budget:
        return text, len(text), len(text), 0
    lines = text.split('\n')
    kept: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + (1 if kept else 0)
        if kept and used + cost > budget:
            break
        kept.append(line)
        used += cost
    return '\n'.join(kept), len(text), used, len(lines) - len(kept)


def cut_head_tail(text: str, budget_bytes: int) -> str:
    """The head and the tail of ``text`` joined by a marker, within ``budget_bytes`` (UTF-8 bytes).

    Text that already fits comes back whole.  Otherwise the middle is cut: ``keep`` characters are kept,
    a third of the budget less a marker's worth (the head and the tail half each).  Four-byte characters
    make that overshoot, so the budget is divided by four instead.  ``''`` means the budget cannot hold a
    useful head and tail, and the caller treats the text as not fitting."""
    if len(text.encode('utf-8')) <= budget_bytes:
        return text
    for divisor in (3, 4):
        keep = budget_bytes // divisor - 30
        if keep < 200:
            return ''
        if keep >= len(text):          # nothing to cut at this size: the marker would count a negative
            continue
        head = keep // 2
        tail = keep - head
        cut = text[:head] + '\n…（中间省略 %d 字）…\n' % (len(text) - keep) + text[len(text) - tail:]
        if len(cut.encode('utf-8')) <= budget_bytes:
            return cut
    return ''
