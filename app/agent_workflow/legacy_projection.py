"""Read-time projection of stored answers that carry the retired legacy check (WP0 step 8).

Three reading surfaces share it: the web replay and the inbox (``agent_chat_stream``), and the Telegram text
(the bridge). It decides what a reader is shown and never what is stored: the callers get new values, the rows
and the protocols are not written back, so the archive keeps its bytes.

The rule, for an answer whose stored protocol holds unverified lines (``unverified_lines``, non-empty):
- the trailing legacy footnote (``number_review.FOOTNOTE``) is removed from the shown text;
- the turn is marked ``legacy_review_retired``.
An answer with no stored unverified lines keeps its text whatever it says: a model that wrote the same sentence
itself is writing prose. An enforce-era footnote (「（另有 N 处…已略去。）」) is marked, not removed, because the
sentences it refers to are gone and cannot be restored.

A brief's line post and its inbox item keep the unverified lines on the run conversation that produced them, so
their rule reads the run's protocol (``source``), found by the run conversation id and the answer's text.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Callable, Mapping, Sequence

from .number_review import FOOTNOTE

RETIRED_FLAG = "legacy_review_retired"
ENFORCE_FOOTNOTE = re.compile(r"\n\n（另有 (\d+) 处表述未能与来源核对，已略去。）")


def _trailing(pattern: re.Pattern, text: str) -> re.Match | None:
    """The last match of ``pattern`` when nothing but whitespace follows it."""
    last = None
    for match in pattern.finditer(text or ""):
        last = match
    if last is not None and not (text[last.end():]).strip():
        return last
    return None


def legacy_footnote(text: str) -> bool:
    return _trailing(FOOTNOTE, text) is not None or _trailing(ENFORCE_FOOTNOTE, text) is not None


def stored_unverified(protocol: Any) -> bool:
    lines = protocol.get("unverified_lines") if isinstance(protocol, Mapping) else None
    return isinstance(lines, list) and bool(lines)


def project_answer(content: str, protocol: Any = None, *, source: Any = None) -> tuple[str, bool]:
    """``(shown text, retired)`` for one stored answer.

    ``protocol`` is the answer's own stored protocol. ``source``, when given, is the protocol that stored the
    answer's unverified lines instead (a brief's post or inbox item: the run's protocol). Neither is changed.
    """
    text = content or ""
    holder = source if source is not None else protocol
    footnote = _trailing(FOOTNOTE, text)
    if stored_unverified(holder):
        if footnote is not None:
            return text[:footnote.start()], True
        return text, True
    if _trailing(ENFORCE_FOOTNOTE, text) is not None:
        return text, True
    return text, False


def stored_run_protocol(conversation_id: Any, body: str) -> dict | None:
    """The protocol of the answer a run stored under ``conversation_id`` whose text starts with ``body``.

    The database read the briefs use: a brief's text is its run's answer, possibly cut to the brief's length.
    None when no such answer exists (the brief is shown as it is stored).
    """
    if not body or not conversation_id:
        return None
    from sqlalchemy import select

    from ..agent_chat_models import AgentMessage
    from ..database import SessionLocal

    try:
        identity = uuid.UUID(str(conversation_id))
    except (TypeError, ValueError):
        return None
    with SessionLocal() as db:
        rows = db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == identity,
                                                     AgentMessage.role == "assistant")
                          .order_by(AgentMessage.sequence.desc()).limit(40)).all()
    for row in rows:
        if isinstance(row.content, str) and row.content.startswith(body):
            return row.tool_calls if isinstance(row.tool_calls, dict) else {}
    return None


Lookup = Callable[[Any, str], Any]


def project_rows(rows: Sequence[Mapping], lookup: Lookup | None = None) -> list[tuple[str, bool]]:
    """``(shown text, retired)`` for each stored row of a replay, in order. Only assistant answers change.

    A line post (``task_post`` protocol) keeps its unverified lines on the run conversation named in the post;
    that protocol is read through ``lookup``, and only when the text ends with a legacy footnote.
    """
    lookup = lookup or stored_run_protocol
    out: list[tuple[str, bool]] = []
    for row in rows:
        content = row.get("content") or ""
        protocol = row.get("tool_calls")
        if row.get("role") != "assistant" or stored_unverified(protocol) or not legacy_footnote(content):
            out.append(project_answer(content, protocol) if row.get("role") == "assistant" else (content, False))
            continue
        marker = protocol.get("task_post") if isinstance(protocol, Mapping) else None
        source = None
        if isinstance(marker, Mapping) and marker.get("run_conversation_id"):
            source = lookup(marker.get("run_conversation_id"), content)
        out.append(project_answer(content, protocol, source=source))
    return out


def project_inbox_items(items: Sequence[dict], lookup: Lookup | None = None) -> list[dict]:
    """The inbox items as shown: a brief's body with the legacy footnote removed where its run stored unverified
    lines, marked ``legacy_review_retired``. Other items, and items whose body has no footnote, are returned as is.
    """
    lookup = lookup or stored_run_protocol
    out: list[dict] = []
    for item in items:
        body = item.get("body") or ""
        if item.get("section") != "brief" or not legacy_footnote(body) or not item.get("conversation_id"):
            out.append(item)
            continue
        shown, retired = project_answer(body, None, source=lookup(item.get("conversation_id"), body))
        out.append({**item, "body": shown, RETIRED_FLAG: True} if retired else item)
    return out
