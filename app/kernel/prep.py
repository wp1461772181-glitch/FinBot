"""The evening-before preparation (5e-2b, design §7.4): every Beijing evening, if a company the owner holds or follows reports within the next
half day, the kernel writes him one 「财报前瞻」: when it is out (Beijing time, by code), what the market expects, the last guidance, his own view
and what to watch.

From Beijing 20:00 to 23:00, once a day (``earnings_prep``).  The companies come from the earnings calendar (``earnings_calendar.reporting_next``);
none → nothing written, no model.  One model turn writes it (``loop.run_wake`` without ``decide``: reads only, no ``act``, no ``ask``) from the
calendar rows, the estimated Beijing release time, his view of each company and the 「系统最新掌握」 block for them; a turn that fails sends a
code-written list instead.  ``FINBOT_DUTY_MODE`` decides as for the morning brief: ``off`` nothing, ``shadow`` written and kept, ``on`` sent
through the outbox (source ``prep``, outside the bot's notify count).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from .. import earnings_calendar, model_usage
from . import loop, prompt, wake

logger = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8))
FIRST_HOUR, LAST_HOUR = 20, 23
SOURCE = "prep"
HEAD = "【财报前瞻】"
WALL_SECONDS = 240        # longer than the loop's own soft limit (loop.SOFT_SECONDS), so its wrap-up comes first, as in the brief
OFF = "值班开关是关的（FINBOT_DUTY_MODE=off）"
NOTHING = "接下来半天没有你持有或关注的公司发财报"


def due_day(now: datetime) -> str | None:
    local = now.astimezone(BEIJING)
    return local.date().isoformat() if FIRST_HOUR <= local.hour < LAST_HOUR else None


def companies(owner: str, day: date) -> list[dict]:
    """The companies reporting next with what the model is given: the calendar line, the Beijing release time and his view."""
    from .. import owner_views
    rows = earnings_calendar.reporting_next(earnings_calendar.tracked_symbols(owner), day)
    views = owner_views.current(owner, [row["symbol"] for row in rows]) if rows else {}
    return [{"symbol": row["symbol"], "company": earnings_calendar._company(row["symbol"]), "calendar": earnings_calendar.line(row),
             "out": earnings_calendar.beijing_release(row), "his_view": (views.get(row["symbol"]) or {}).get("text")} for row in rows]


def fallback_text(items: list[dict]) -> str:
    lines = []
    for item in items:
        lines.append(f"{item['company']}：{item['out']}")
        lines.append(f"  {item['calendar']}")
        if item.get("his_view"):
            lines.append(f"  你的看法：{item['his_view']}")
    return "\n".join(lines)


def _known(symbols: list[str], now: datetime) -> str | None:
    """The 「系统最新掌握」 block for these companies (the last quarter, its guidance, the latest filings and news), built three companies at a
    time (the block's own limit is three companies and 2,000 characters, so a busy evening is several blocks, not one with companies dropped);
    None when nothing could be built.  A company the block leaves out is the model's to read with its tools (the prompt says so)."""
    from .. import latest_known
    parts = []
    for start in range(0, len(symbols), latest_known.MAX_COMPANIES):
        try:
            items = latest_known.gather(symbols[start:start + latest_known.MAX_COMPANIES], now=now, with_facts=True)
            text, _ = latest_known._render(items, now, [], None)
        except Exception:
            logger.warning("earnings prep: the latest-known block could not be built", exc_info=True)
            continue
        if text:
            parts.append(text)
    return "\n\n".join(parts) or None


async def _write(owner: str, day: str, items: list[dict], now: datetime) -> dict:
    turn_id = str(uuid.uuid4())
    recorder, holder, result, failure = wake.Recorder(), {}, None, None
    facts = {"now_beijing": now.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")}
    known = await asyncio.to_thread(_known, [item["symbol"] for item in items], now)

    async def turn():
        bot, context = await wake.duty_context(owner, holder)
        messages = prompt.build_prep_messages(context, items, facts, known)
        with model_usage.purpose("duty", owner_hash=owner, conversation_id=holder["conversation"], bot_id=bot.id, turn_id=turn_id, job=f"prep:{day}"):
            return await loop.run_wake(context, recorder.emit, messages, turn_id=turn_id, decide_tool=False)
    try:
        result = await asyncio.wait_for(turn(), WALL_SECONDS)
    except TimeoutError:
        failure = f"超过 {WALL_SECONDS} 秒还没有写完"
    except Exception as exc:
        logger.warning("earnings prep %s: the model turn failed: %s", day, wake._code(exc), exc_info=not hasattr(exc, "detail"))
        failure = f"模型这次没有写成：{wake._code(exc)}"
    answer = ((result or {}).get("answer") or "").strip()
    if result is not None and (result.get("reason") == "empty_answer" or not answer):
        failure = "模型没有写出正文"          # the loop's 「这次没能生成回答」 is no preview to send
    audit = (result or {}).get("audit") or {}
    if holder.get("conversation"):
        from ..agent_recall import TASK_POST_HEAD
        protocol = {"route": "K", **((result or {}).get("final_protocol") or {}),
                    "audit": audit or {"engine": "v2", "terminal_status": "failed", "model_calls": 0, "calls": []},
                    "citations": (result or {}).get("citations") or [], "unattended": True, "prep": True}
        try:
            await asyncio.to_thread(wake._store_turn, owner, holder["conversation"], turn_id, f"{TASK_POST_HEAD}财报前瞻 {day}", recorder, protocol,
                                    answer or failure or "没有结果。", result is None)
        except Exception:
            logger.exception("earnings prep %s: the turn could not be stored", day)
    return {"body": answer if not failure else fallback_text(items), "reason": f"{failure}，改发原样列表。" if failure else None,
            "turn_id": turn_id if holder.get("conversation") else None, "model_calls": int(audit.get("model_calls") or 0)}


async def run_once(owner: str, now: datetime, *, day: str | None = None) -> dict | None:
    """Write tonight's preparation if it is due and not written yet; the ``earnings_prep`` row, or None (not due, or taken).  ``day`` is for a
    replay (skips the time check).  Never raises after the day is claimed."""
    day = day or due_day(now)
    if day is None or await asyncio.to_thread(earnings_calendar.prep_taken, owner, day):
        return None
    current = wake.mode()
    row_id = await asyncio.to_thread(earnings_calendar.prep_claim, owner, day, current)
    if row_id is None:
        return None

    def finish(**fields):
        return earnings_calendar.prep_finish(row_id, **fields)
    try:
        if current == "off":
            return await asyncio.to_thread(lambda: finish(outcome="skipped_off", reason=OFF))
        items = await asyncio.to_thread(companies, owner, date.fromisoformat(day))
        if not items:
            return await asyncio.to_thread(lambda: finish(outcome="skipped", reason=NOTHING))
        written = await _write(owner, day, items, now)
        message = HEAD + written["body"]
        fields = {"symbols": ",".join(item["symbol"] for item in items)[:200], "message": message, "reason": written["reason"],
                  "turn_id": written["turn_id"], "model_calls": written["model_calls"]}
        if current == "on":
            group, why = await asyncio.to_thread(lambda: wake._deliver(owner, message, source=SOURCE, cap=False))
            fields["delivery"] = why
            if why != "queued":
                fields["reason"] = f"写好了但没能排进发件箱：{why}"
                return await asyncio.to_thread(lambda: finish(outcome="failed", **fields))
        return await asyncio.to_thread(lambda: finish(outcome="done", **fields))
    except Exception as exc:
        logger.exception("earnings prep %s failed", day)
        return await asyncio.to_thread(lambda: finish(outcome="failed", reason=f"出错了：{type(exc).__name__}"))
