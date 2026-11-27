"""5d-1: after a kernel answer has gone out, its figures are checked against what the turn read.  Nothing in the answer changes.

The check is the old deterministic one (no model call): what ``unverified.line_numbers`` rejects line by line, kept only where no source
of the conversation states the figure at all and it is not the sources' or the user's arithmetic.  The result is kept on the stored
answer under ``tool_calls.reconciliation`` and shown in the backstage and in the chat's 「来源」 panel; the answer itself is never marked.

``reconcile`` is the check; ``check_and_store`` is the background job the stream schedules (``agent_chat_stream``); ``kernel_answers`` and
``inputs_of`` give ``scripts/reconcile_report.py`` the same inputs the job reads.
"""
from __future__ import annotations

import json
import logging
import re
import uuid

log = logging.getLogger(__name__)

VERSION = 1
KEY = "reconciliation"
LINE_CHARS = 200
EARLIER_ANSWERS = 20     # the earlier answers of the conversation whose sources still count
_ALL = 1_000_000          # answer_scope cuts its lists to ``limit``; the check wants all of them


def _value_text(value) -> str:
    """A figure as written for a reader: 8888, 12.5 (the checker rounds to 4 places)."""
    number = float(value)
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _scaled(holders: list[dict]) -> set:
    """The figures of the sources whose own text says its table is in thousands, millions or billions, in that unit (the old check's
    ``evidence._SCALE``: a table states 81,615 under "(In millions)" for 81,615 百万).  A source that names no unit scales nothing."""
    from ..agent_workflow import evidence
    out: set = set()
    for citation in holders:
        scanned = str(citation.get("check_text") or citation.get("quote") or "")
        for marker, scale in evidence._SCALE:
            if marker.search(scanned):
                out |= {round(v * scale, 4) for v in evidence._figures_of(scanned) if v >= 1}
    return out


def _held(value: float, pool: set, scaled: set) -> bool:
    """Whether some source states ``value``: as written, or in the unit its table names."""
    return value in pool or value in scaled


_UNITS = (1e3, 1e6, 1e9)


def _operand(value: float, pool: set, scaled: set, said: set) -> bool:
    """Whether a figure the line writes may take part in its own arithmetic: a source states it (also where the line writes in
    millions what the source states in full: 「4,751」 for 「4,751 百万美元」, a ratio is the same in either unit), or the user did."""
    return _held(value, pool, scaled) or value in said or any(round(value * unit, 4) in pool for unit in _UNITS)


# Digits that are not amounts and must not take part in the arithmetic or the restating rule: a citation marker, a date, a clock time.
_NOT_AMOUNTS = re.compile(r"\[\d+\]|(?:\d{2,4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*[日号]|\d{2,4}\s*年\s*\d{1,2}\s*月|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
                          r"|(?<![\d.])\d{1,2}/\d{1,2}(?![\d/])|(?<![\d.:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])")


def _amounts(line: str) -> set:
    """The amounts a line writes, with markers, dates and clock times left out."""
    from ..agent_workflow import evidence
    return {r["value"] for r in evidence._figure_records(_NOT_AMOUNTS.sub(" ", line))}


def _product(record: dict, pool: list) -> bool:
    """``value`` = a × b for two pool figures (price × shares), within ``evidence``'s false-accept bound as the amount closure counts it."""
    from ..agent_workflow import evidence
    digits, n = record["digits"], len(pool)
    if n < 2 or record["pct"]:
        return False
    if n * (n - 1) // 2 + n > evidence.CLOSURE_FALSE_ACCEPT_BOUND * 18 * 10 ** (digits - 1):
        return False
    target = evidence._round_to(record["value"], digits)
    return any(evidence._round_to(a * b, digits) == target for i, a in enumerate(pool) for b in pool[i:])


def _derived(token: str, pool: set, verified) -> bool:
    """Whether the written figure ``token`` is the sum, difference, ratio, change or product of figures the sources state
    (``evidence._closure`` and ``_product``, with the same false-accept bound)."""
    from ..agent_workflow import evidence
    records = evidence._figure_records(token)
    operands = evidence._operand_pool(pool) + sorted(v for v in pool if v == int(v) and 1 < v <= 10_000)   # shares are small integers
    operands = sorted(set(operands))
    return bool(records) and all(evidence._closure(record, pool, set(verified or ())) is not None or _product(record, operands)
                                 for record in records)


def reconcile(answer: str, citations: list[dict], *, question: str, user_text: str, earlier: list[dict] | None = None) -> dict:
    """``{"version", "figures", "flagged": [{"line", "values"}]}`` for one answer; ``{"version", "error"}`` when the check fails.

    A figure is flagged only when no source of the turn states it at all.  Each line is read as the old check reads it
    (``evidence._reviewable_lines``: a table row inherits its table's markers); ``unverified.line_numbers`` gives the figures the
    per-sentence review rejects there (it lets through the user's own figures and the sum, difference, ratio or change of the sources'
    figures within its false-accept bound, in a sentence with ``[n]`` and, for the backstop kinds, in one without); of those only the
    ones no citation holds are kept (a figure that sits in a source other than the cited one is a citation slip, not a fabrication).
    ``figures`` is how many figures were held against the sources (``answer_scope``'s counts).  Never raises."""
    try:
        from ..agent_workflow import evidence, unverified
        cites = [c for c in citations or [] if isinstance(c, dict)]
        question, user_text = question or "", user_text or ""
        verified = evidence.answer_verified_figures(answer or "", cites, question=question, user_text=user_text)
        # the sources an earlier turn of the conversation read count too: the model may restate what it found a turn ago
        before = [c for c in earlier or [] if isinstance(c, dict)]
        holders = cites + before
        pool = set()
        for citation in holders:
            pool |= evidence._figures_of(evidence.citation_check_text(citation))
        scaled = _scaled(holders)
        said = evidence.user_figure_values(user_text)
        grouped: dict[str, list[str]] = {}
        passed: set = set()          # figures worked out from the sources on some line (not one the sources or the user state)
        for _, stripped, checked in evidence._reviewable_lines(answer or "", cites):
            if checked is None:
                continue          # a table header or rule is not a claim
            # the line as the old check reads it (a table row inherits its table's markers): the figures it rejects there, then
            # only those no source of the conversation holds at all
            _, written = unverified.line_numbers(checked, cites, user_text=user_text, verified=verified)
            missing = [token for token, values in written if not any(_held(v, pool, scaled) for v in values)]
            if missing:
                # arithmetic: first on the line's own figures that a source or the user states (price × shares, a written-out ratio; a pool
                # that small stays well inside the false-accept bound where the whole turn's figures would not), then on all the sources'
                # figures (same closure and false-accept bound as the old check)
                flagged = {r["value"] for t in missing for r in evidence._figure_records(t)}      # a figure still in question vouches for nothing
                near = {v for v in _amounts(checked) if v not in flagged and (_operand(v, pool, scaled, said) or v in passed)} | said
                derived = [token for token in missing if _derived(token, near, near) or _derived(token, pool, verified)]
                missing = [token for token in missing if token not in derived]
                # an estimate does not become evidence by being repeated (``answer_verified_figures``): a labelled inference's own
                # figures pass where they are, not where the answer restates them
                if not evidence.is_inference_label(stripped):
                    passed |= {r["value"] for t in derived for r in evidence._figure_records(t)}
            if not missing:
                continue
            values = grouped.setdefault(str(stripped).strip()[:LINE_CHARS], [])
            for token in missing:
                if token not in values:
                    values.append(token)
        # a figure worked out on one line (a table row) is the same figure when the answer restates it elsewhere
        for line in list(grouped):
            grouped[line] = [t for t in grouped[line] if not {r["value"] for r in evidence._figure_records(t)} <= passed]
            if not grouped[line]:
                del grouped[line]
        counts = evidence.answer_scope(answer or "", cites, question=question, user_text=user_text, verified=verified)["counts"]
        figures = int(counts.get("marked_figures", 0)) + int(counts.get("unmarked_backstopped", 0))
        return {"version": VERSION, "figures": figures, "flagged": [{"line": line, "values": values} for line, values in grouped.items()]}
    except Exception as exc:  # noqa: BLE001 - the check never fails the job that runs it
        return {"version": VERSION, "error": type(exc).__name__}


# --- the stored answer ---------------------------------------------------------------------------------------------

def _record(value) -> dict:
    """A stored ``tool_calls`` as a dict (text is parsed; anything else is no record)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def inputs_of(db, row) -> dict:
    """What the check reads for one stored answer: its text, the citations stored with it (they keep their check text up to
    ``evidence.STORED_CHECK_TEXT_CHARS``), the turn's first user message as the question, and everything the person typed in the
    conversation up to the answer (the rule of ``Turn.user_stated_text``: no card button values)."""
    from sqlalchemy import func, select
    from ..agent_chat_models import AgentMessage
    from ..agent_workflow.direct import CONTROL_PREFIXES
    M = AgentMessage
    citations = _record(row.tool_calls).get("citations")
    typed = db.execute(select(M.turn_id, M.content).where(M.conversation_id == row.conversation_id, M.role == "user",
                                                           M.sequence <= row.sequence).order_by(M.sequence)).all()
    said = [content for _, content in typed if isinstance(content, str) and content and not content.startswith(CONTROL_PREFIXES)]
    question = next((content for turn, content in typed if turn == row.turn_id and isinstance(content, str)), "")
    earlier: list[dict] = []
    # answers, not tool rounds (stored as assistant rows with no text): a turn with many lookups must not push the earlier answers out
    for stored in db.scalars(select(M.tool_calls).where(M.conversation_id == row.conversation_id, M.role == "assistant",
                                                         M.sequence < row.sequence, func.btrim(func.coalesce(M.content, "")) != "")
                             .order_by(M.sequence.desc()).limit(EARLIER_ANSWERS)):
        found = _record(stored).get("citations")
        earlier.extend(c for c in found if isinstance(c, dict)) if isinstance(found, list) else None
    return {"answer": row.content or "", "citations": citations if isinstance(citations, list) else [],
            "question": question, "user_text": "\n".join(said), "earlier": earlier}


def check(message_id) -> dict | None:
    """The check of one stored assistant message, or None when there is no such row."""
    from ..agent_chat_models import AgentMessage
    from ..database import SessionLocal
    with SessionLocal() as db:
        row = db.get(AgentMessage, uuid.UUID(str(message_id)))
        if row is None or row.role != "assistant":
            return None
        inputs = inputs_of(db, row)
    return reconcile(inputs["answer"], inputs["citations"], question=inputs["question"], user_text=inputs["user_text"], earlier=inputs["earlier"])


def store(message_id, result: dict) -> bool:
    """Merge ``result`` into the stored message's protocol under ``reconciliation``; every other key stays.  False when the row is gone."""
    from sqlalchemy import select
    from ..agent_chat_models import AgentMessage
    from ..database import SessionLocal
    with SessionLocal() as db:
        row = db.scalar(select(AgentMessage).where(AgentMessage.id == uuid.UUID(str(message_id))).with_for_update())
        if row is None:
            return False
        row.tool_calls = {**_record(row.tool_calls), KEY: result}
        db.commit()
        return True


def check_and_store(message_id) -> None:
    """The background job of one kernel answer (run in a thread; the response never waits for it).  A failure to read or write is
    logged and leaves no key; a check that failed is stored as its ``error``."""
    try:
        result = check(message_id)
        if result is None:
            log.warning("reconcile: no stored answer %s", message_id)
            return
        if "error" in result:
            log.warning("reconcile: the check of %s failed (%s)", message_id, result["error"])
        store(message_id, result)
    except Exception:  # noqa: BLE001 - logged; the answer is untouched
        log.exception("reconcile: checking answer %s failed", message_id)


def kernel_answers(db, limit: int) -> list:
    """The newest stored kernel answers (assistant rows whose protocol route is ``K``, stored complete with text), newest first."""
    from sqlalchemy import Text, cast, func, select
    from sqlalchemy.dialects.postgresql import JSONB
    from ..agent_chat_models import AgentMessage
    M = AgentMessage
    # A stored NUL escape is legal JSON but not jsonb (the backstage list does the same swap).
    record = cast(func.replace(cast(M.tool_calls, Text), "\\u0000", "\\u0020"), JSONB)
    return list(db.scalars(select(M).where(M.role == "assistant", M.status == "complete", func.btrim(func.coalesce(M.content, "")) != "",
                                           func.jsonb_extract_path_text(record, "route") == "K",
                                           # wake and brief turns are the duty's own records, not answers he asked for (the live job never sees them)
                                           func.coalesce(func.jsonb_extract_path_text(record, "unattended"), "false") != "true")
                           .order_by(M.created_at.desc(), M.id.desc()).limit(limit)))
