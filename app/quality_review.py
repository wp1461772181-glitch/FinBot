"""The weekly self-check (5d-3c, design §10.2): the answers the owner marked 「不好」 this week, sorted by what went wrong.

A job of the memory calendar (``memory_schedule.JOBS["weekly_quality"]``): once a week it gathers his 「不好」 verdicts of the period
(``answer_feedback``) with the question, the answer, his reason and what the turn used (its tools and their errors), and asks the ``judge``
role's model to put each in one of ``CATEGORIES`` with one sentence why, and to say in a few sentences what to fix first.  A week with none
writes an empty report and asks no model.  The report is kept in ``quality_reports`` and shown in the backstage 质量 tab; nothing is sent
to him, nothing in the answers or the memory changes.

The model's sorting is trusted (it is a reading, not a fact): a category outside the list becomes 「其他」 and an answer it skipped is
listed as unsorted.  Only an answer that is not JSON at all fails the run (the calendar tries again in six hours).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import JSON, DateTime, Integer, String, Text, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from . import agent_model_roles as roles
from .database import Base, SessionLocal

log = logging.getLogger(__name__)

JOB = "weekly_quality"
TITLE = "每周自检"
CATEGORIES = ("缺数据", "工具没用对", "想得太浅", "记错偏好", "说得不清楚", "其他")
OTHER = "其他"
UNSORTED = "没归类"
ROLE = "judge"                   # judging answers is the judge's work; the backstage settings already choose its model
TIMEOUT_SECONDS = 120
ANSWER_CHARS = 1500
QUESTION_CHARS = 400
MAX_ITEMS = 40                   # a week with more 「不好」 than this sends the newest 40 (the count says how many there were)
WHY_CHARS = 120
NEXT_CHARS = 600
DEFAULT_DAYS = 7

PROMPT = (
    "你是 FinBot 的质量复盘助手。下面是用户这一周点了「不好」的回答，每条有编号、他的提问、回答（可能被截断）、他说的原因（可能没有）、"
    "这一轮用过的工具和出错的工具。\n"
    "请把每条归到下面一类：" + "、".join(CATEGORIES) + "。\n"
    "- 缺数据：需要的数据没有、太旧，或者查不到。\n"
    "- 工具没用对：该用的工具没用、用错了、参数错了，或者工具出错后没处理好。\n"
    "- 想得太浅：数据有，但分析不够、漏了关键对比或结论。\n"
    "- 记错偏好：没按他说过的偏好或习惯来（单位、格式、详略、关注点）。\n"
    "- 说得不清楚：内容没错，但没讲清楚、太啰嗦，或者关键信息（日期、口径）没放在显眼处。\n"
    "- 其他：都不像。\n"
    "每条给一句为什么（看他的原因和回答本身，不要编）。最后用两三句话说：这一周最该先改哪里。\n"
    "只输出 JSON：{\"items\": [{\"id\": 编号, \"category\": \"类别\", \"why\": \"一句话\"}], \"next\": \"两三句话\"}"
)


class QualityReport(Base):
    """One weekly self-check: the period it covers, how many answers he marked good and 不好 in it, each 不好 with its category and why, and
    what to fix first.  ``status``: ``done`` (sorted by the model), ``empty`` (no 不好 that week: no model asked)."""
    __tablename__ = "quality_reports"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    good: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)          # [{message_id, at, question, reason, category, why}]
    categories: Mapped[dict | None] = mapped_column(JSON, nullable=True)     # {category: count}
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)


def days() -> int:
    try:
        return max(1, int(os.getenv("FINBOT_QUALITY_DAYS", "").strip() or DEFAULT_DAYS))
    except ValueError:
        return DEFAULT_DAYS


def _clip(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _turn_tools(db, conversation_id, turn_id) -> tuple[list[str], list[str]]:
    """The tools the turn called and the ones whose result was not ok (``ok: false`` with its error code)."""
    from .agent_chat_models import AgentMessage
    rows = db.execute(select(AgentMessage.role, AgentMessage.tool_calls, AgentMessage.content).where(
        AgentMessage.conversation_id == conversation_id, AgentMessage.turn_id == turn_id).order_by(AgentMessage.sequence)).all()
    used, failed = [], []
    names: dict[str, str] = {}
    for role, record, content in rows:
        if role == "assistant" and isinstance(record, dict):
            for call in record.get("calls") or []:
                function = (call or {}).get("function") or {}
                name = str(function.get("name") or "")
                if name:
                    used.append(name)
                    names[str(call.get("id") or "")] = name
        elif role == "tool":
            try:
                result = json.loads(content or "")
            except ValueError:
                continue
            if isinstance(result, dict) and result.get("ok") is False:
                failed.append(str(result.get("error_code") or "error"))
    return list(dict.fromkeys(used)), list(dict.fromkeys(failed))


def gather(owner_hash: str, since: datetime, until: datetime) -> tuple[list[dict], int, int]:
    """His 不好 answers rated in ``[since, until)`` (newest first, at most ``MAX_ITEMS``) with what the model needs, and how many good and bad
    verdicts he gave in the period."""
    from .agent_chat_models import AgentConversation, AgentMessage
    from .answer_feedback import AnswerFeedback as AF
    with SessionLocal() as db:
        rows = db.execute(select(AF, AgentMessage.content, AgentMessage.created_at).join(AgentMessage, AgentMessage.id == AF.message_id)
                          .join(AgentConversation, AgentConversation.id == AF.conversation_id)
                          .where(AF.owner_hash == owner_hash, AgentConversation.owner_hash == owner_hash, AF.updated_at >= since, AF.updated_at < until)
                          .order_by(AF.updated_at.desc(), AF.id.desc())).all()
        good = sum(1 for feedback, _, _ in rows if feedback.verdict == "good")
        bad_rows = [row for row in rows if row[0].verdict == "bad"]
        items = []
        for feedback, answer, at in bad_rows[:MAX_ITEMS]:
            question = db.scalar(select(AgentMessage.content).where(AgentMessage.conversation_id == feedback.conversation_id,
                                                                     AgentMessage.turn_id == feedback.turn_id, AgentMessage.role == "user")
                                 .order_by(AgentMessage.sequence).limit(1))
            used, failed = _turn_tools(db, feedback.conversation_id, feedback.turn_id)
            items.append({"message_id": str(feedback.message_id), "at": at.isoformat() if at else None, "question": _clip(question, QUESTION_CHARS),
                          "answer": _clip(answer, ANSWER_CHARS), "reason": feedback.reason, "tools": used, "tool_errors": failed})
    return items, good, len(bad_rows)


def _user_text(items: list[dict]) -> str:
    blocks = []
    for number, item in enumerate(items, 1):
        blocks.append("\n".join([f"【{number}】", f"提问：{item['question'] or '（没有）'}", f"回答：{item['answer'] or '（没有）'}",
                                 f"他的原因：{item['reason'] or '（没写）'}", f"用过的工具：{'、'.join(item['tools']) or '（没有）'}",
                                 f"出错的工具：{'、'.join(item['tool_errors']) or '（没有）'}"]))
    return "\n\n".join(blocks)


def _complete(owner_hash: str, system: str, user: str) -> tuple[str, str]:
    """One call to the judge role's model (the server default when unset); its text and the model's name."""
    from .agent_chat_provider import decision_request
    model = roles.resolve(owner_hash, ROLE)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def call():
        async with asyncio.timeout(TIMEOUT_SECONDS):
            return await decision_request(model["provider"], model["model"], model["api_key"], messages, [], model.get("base_url"),
                                          **({"catalog_name": model["name"]} if model.get("name") else {}))
    _data, message = asyncio.run(call())
    return (str(message.get("content") or "") if isinstance(message, dict) else ""), str(model.get("name") or model.get("model") or "")


def _json_object(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        found = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def sort_items(items: list[dict], found: dict) -> tuple[list[dict], dict, str | None]:
    """Each item with the model's category and why (a category outside the list is 其他; one it skipped is 没归类), the count per category, and
    what to fix first."""
    sorted_by = {}
    for entry in found.get("items") or []:
        if not isinstance(entry, dict):
            continue
        try:
            number = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        category = entry.get("category") if entry.get("category") in CATEGORIES else OTHER
        sorted_by.setdefault(number, {"category": category, "why": _clip(entry.get("why"), WHY_CHARS) or None})
    out, counts = [], {}
    for number, item in enumerate(items, 1):
        verdict = sorted_by.get(number) or {"category": UNSORTED, "why": None}
        counts[verdict["category"]] = counts.get(verdict["category"], 0) + 1
        out.append({"message_id": item["message_id"], "at": item["at"], "question": item["question"], "reason": item["reason"], **verdict})
    next_step = _clip(found.get("next"), NEXT_CHARS) or None
    return out, counts, next_step


def _store(owner_hash: str, since: datetime, until: datetime, status: str, good: int, bad: int, items=None, counts=None, next_step=None, model=None) -> None:
    with SessionLocal() as db:
        db.add(QualityReport(owner_hash=owner_hash, period_start=since, period_end=until, status=status, good=good, bad=bad, items=items,
                             categories=counts, next_step=next_step, model=model))
        db.commit()


def run(owner_hash: str, now: datetime, last_run_at: datetime | None) -> dict:
    """The calendar's job: the self-check of the period since the last run (at most ``days()`` back; the first run looks back that far)."""
    until = now
    since = max(last_run_at, now - timedelta(days=days())) if last_run_at else now - timedelta(days=days())
    items, good, bad = gather(owner_hash, since, until)
    if not items:
        _store(owner_hash, since, until, "empty", good, bad)
        return {"outcome": "done", "reason": "这一周没有被点「不好」的回答"}
    raw, model = _complete(owner_hash, PROMPT, _user_text(items))
    found = _json_object(raw)
    if found is None:
        return {"outcome": "failed", "reason": "模型没有给出可读的归类"}
    sorted_items, counts, next_step = sort_items(items, found)
    _store(owner_hash, since, until, "done", good, bad, sorted_items, counts, next_step, model)
    return {"outcome": "done", "reason": f"归类了 {len(sorted_items)} 条"}


def recent(owner_hash: str, limit: int = 8) -> list[dict]:
    """The newest reports, newest first, for the backstage."""
    with SessionLocal() as db:
        rows = db.scalars(select(QualityReport).where(QualityReport.owner_hash == owner_hash)
                          .order_by(QualityReport.created_at.desc()).limit(limit)).all()
    return [{"id": str(row.id), "created_at": row.created_at.isoformat(), "period_start": row.period_start.isoformat(),
             "period_end": row.period_end.isoformat(), "status": row.status, "good": row.good, "bad": row.bad,
             "items": row.items or [], "categories": row.categories or {}, "next": row.next_step, "model": row.model} for row in rows]
