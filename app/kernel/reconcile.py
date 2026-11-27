"""5d-1: after a kernel answer has gone out, its figures are checked against what the turn read.  Nothing in the answer changes.

The check is the old deterministic one (no model call): what ``evidence.number_check`` rejects, kept only where no source of the turn states
the figure at all (``unverified.entries``).  Legitimate arithmetic and the user's own figures pass.  The result is kept on
the stored answer under ``tool_calls.reconciliation`` and shown in the backstage only.

``reconcile`` is the check; ``check_and_store`` is the background job the stream schedules (``agent_chat_stream``); ``kernel_answers`` and
``inputs_of`` give ``scripts/reconcile_report.py`` the same inputs the job reads.
"""
from __future__ import annotations

import json
import logging
import uuid

log = logging.getLogger(__name__)

VERSION = 1
KEY = "reconciliation"
LINE_CHARS = 200
_ALL = 1_000_000          # answer_scope cuts its lists to ``limit``; the check wants all of them


def _value_text(value) -> str:
    """A figure as written for a reader: 8888, 12.5 (the checker rounds to 4 places)."""
    number = float(value)
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _derived(token: str, pool: set, verified) -> bool:
    """Whether the written figure ``token`` is the sum, difference, ratio or change of figures the turn's sources state
    (``evidence._closure``, with its false-accept bound)."""
    from ..agent_workflow import evidence
    records = evidence._figure_records(token)
    return bool(records) and all(evidence._closure(record, pool, set(verified or ())) is not None for record in records)


def reconcile(answer: str, citations: list[dict], *, question: str, user_text: str) -> dict:
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
        pool = set()
        for citation in cites:
            pool |= evidence._figures_of(evidence.citation_check_text(citation))
        grouped: dict[str, list[str]] = {}
        for _, stripped, checked in evidence._reviewable_lines(answer or "", cites):
            if checked is None:
                continue          # a table header or rule is not a claim
            # the line as the old check reads it (a table row inherits its table's markers): the figures it rejects there, then
            # only those no citation of the turn holds at all
            _, written = unverified.line_numbers(checked, cites, user_text=user_text, verified=verified)
            missing = [token for token, values in written if not any(unverified._holders(v, cites) for v in values)]
            # a sentence with no [n] cites no source, so the review had nothing to derive from: a sum, difference, ratio or change of
            # any source's figures is the model's own arithmetic, not a figure from nowhere (same closure and false-accept bound)
            missing = [token for token in missing if not _derived(token, pool, verified)]
            if not missing:
                continue
            values = grouped.setdefault(str(stripped).strip()[:LINE_CHARS], [])
            for token in missing:
                if token not in values:
                    values.append(token)
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
    from sqlalchemy import select
    from ..agent_chat_models import AgentMessage
    from ..agent_workflow.direct import CONTROL_PREFIXES
    M = AgentMessage
    citations = _record(row.tool_calls).get("citations")
    typed = db.execute(select(M.turn_id, M.content).where(M.conversation_id == row.conversation_id, M.role == "user",
                                                           M.sequence <= row.sequence).order_by(M.sequence)).all()
    said = [content for _, content in typed if isinstance(content, str) and content and not content.startswith(CONTROL_PREFIXES)]
    question = next((content for turn, content in typed if turn == row.turn_id and isinstance(content, str)), "")
    return {"answer": row.content or "", "citations": citations if isinstance(citations, list) else [],
            "question": question, "user_text": "\n".join(said)}


def check(message_id) -> dict | None:
    """The check of one stored assistant message, or None when there is no such row."""
    from ..agent_chat_models import AgentMessage
    from ..database import SessionLocal
    with SessionLocal() as db:
        row = db.get(AgentMessage, uuid.UUID(str(message_id)))
        if row is None or row.role != "assistant":
            return None
        inputs = inputs_of(db, row)
    return reconcile(inputs["answer"], inputs["citations"], question=inputs["question"], user_text=inputs["user_text"])


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
                                           func.jsonb_extract_path_text(record, "route") == "K")
                           .order_by(M.created_at.desc(), M.id.desc()).limit(limit)))
