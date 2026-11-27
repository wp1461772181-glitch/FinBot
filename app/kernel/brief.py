"""The morning brief: every morning (Beijing 08:05) the kernel writes the owner one message about what its duty kept overnight.

It covers the duty rows since the last brief that ran (else from 24 hours before the first brief row, else the last 24 hours): the alerts the wake chose to keep for the brief
(``digest``), the follow-ups it wrote at night but did not send (``tell_now`` held over the night), and one line, written by code, of
how many alerts it looked at and decided not to bother him with.  The kept and held items go to one model turn (``loop.run_wake``
without ``decide``: reads only, no ``act``, no ``ask``); a turn that fails still sends what was kept, as a plain list.  Only filtered
rows means no model call; no rows at all means no brief.  The findings of the missed-alert checks done in the window (``kernel.selfcheck``)
are added as code-written lines after the body; the model is not given them.

``FINBOT_DUTY_MODE`` decides as it does for the wake: ``off`` no brief, ``shadow`` written and logged, ``on`` sent through the outbox
(source ``brief``: neither the duty messages' daily count nor the bot's notify count; a brief that cannot be queued is ``failed``, so the next
one carries the same rows).  Every day that is due leaves one ``duty_brief``
row whatever happened; the turn is stored in the owner's hidden duty conversation like a wake turn.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from .. import duty_brief, duty_log, duty_selfcheck, model_usage
from . import loop, prompt, wake

logger = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8))
DUE_AT = (8, 5)
LAST_HOUR = 12
WINDOW_DEFAULT = timedelta(hours=24)
SOURCE = "brief"
HEAD = "【早间简报】"
TEXT_MAX = 300        # alert text per kept item
WALL_SECONDS = 240    # longer than loop.SOFT_SECONDS, so the loop's own wrap-up comes first
COUNT_KEYS = ("digest", "held", "record", "ignore", "told", "failed")
NOTHING = "从上次简报到现在没有值班记录。"
NOTHING_TO_SAY = "从上次简报到现在没有要写进简报的事（只有已经发出的或没有完成的值班记录）。"
OFF = "值班功能关着（FINBOT_DUTY_MODE=off），没有写简报。"
FALLBACK_HEAD = "这份简报没能由我来写，先把夜里留给你的事原样列出："
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
MINUTE = "%Y-%m-%d %H:%M"


def beijing(value) -> str | None:
    """``value`` (aware datetime or ISO string) as Beijing time to the minute; None when missing."""
    if not value:
        return None
    when = datetime.fromisoformat(value) if isinstance(value, str) else value
    return when.astimezone(BEIJING).strftime(MINUTE)


def facts(now: datetime, since: datetime, night_digest_sent: bool) -> dict:
    """The 「现在」 block: the time now, the window's start (both Beijing) and whether the 08:00 night digest went out."""
    local = now.astimezone(BEIJING)
    return {"now": f"{local.strftime(MINUTE)} {WEEKDAYS[local.weekday()]}", "since": beijing(since), "night_digest_sent": bool(night_digest_sent)}


def due_day(now: datetime) -> str | None:
    """The Beijing date when ``now`` (aware) is between 08:05 inclusive and 12:00 exclusive Beijing, else None."""
    local = now.astimezone(BEIJING)
    if (local.hour, local.minute) >= DUE_AT and local.hour < LAST_HOUR:
        return local.date().isoformat()
    return None


def gather(owner_hash: str, since: datetime) -> dict:
    """The duty rows after ``since`` as what the brief carries (``kept``, ``held``), what it counts, and whether any was held for the night
    digest (the sentinel sends its 08:00 digest only when it held an alert)."""
    counts = dict.fromkeys(COUNT_KEYS, 0)
    kept: list[dict] = []
    held: list[dict] = []
    night_digest_sent = False
    for row in duty_log.since(owner_hash, since):
        event = row["event"] or {}
        if event.get("deferred"):
            night_digest_sent = True
        if row["outcome"] != "decided":
            counts["failed"] += 1
            continue
        text = event.get("text") if isinstance(event.get("text"), str) else ""
        decision = row["decision"]
        at = beijing(row["created_at"])
        if decision == "digest":
            counts["digest"] += 1
            kept.append({"symbol": event.get("symbol"), "text": text[:TEXT_MAX], "reason": row["reason"], "at": at})
        elif decision == "tell_now" and row["delivery"] == wake.HELD_NIGHT:
            counts["held"] += 1
            held.append({"id": row["id"], "symbol": event.get("symbol"), "text": text[:TEXT_MAX], "message": row["message"], "at": at})
        elif decision == "tell_now" and row["delivery"] == "queued":
            counts["told"] += 1
        elif decision in ("record", "ignore"):
            counts[decision] += 1
    findings, selfcheck_ids = missed_findings(owner_hash)
    return {"kept": kept, "held": held, "counts": counts, "night_digest_sent": night_digest_sent, "findings": findings, "selfcheck_ids": selfcheck_ids}


def missed_findings(owner_hash: str) -> tuple[list[dict], list[int]]:
    """The findings of the missed-alert checks no brief has carried yet (``kernel.selfcheck``), oldest first, each ``(kind, symbol, at)``
    once, and those checks' row ids.  Not windowed: a check that ends after the day's brief is carried by the next one.  A log that cannot
    be read costs the brief nothing but these lines."""
    try:
        rows = duty_selfcheck.unbriefed(owner_hash)
    except Exception:
        logger.exception("morning brief: the missed-alert checks could not be read")
        return [], []
    out, seen = [], set()
    for row in rows:
        for finding in row.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            key = (finding.get("kind"), finding.get("symbol"), finding.get("at"))
            if key not in seen:
                seen.add(key)
                out.append(finding)
    return out, [row["id"] for row in rows]


def selfcheck_lines(findings: list[dict]) -> str:
    """The lines code writes about what the missed-alert check found; empty when nothing was found."""
    if not findings:
        return ""
    lines = ["漏报自查（每天收盘后核对，代码写的）："]
    for f in findings:
        symbol, at = f.get("symbol") or "", f.get("at") or ""
        if f.get("kind") == "earnings":
            url = f.get("url") or ""
            lines.append(f"· {symbol} 的财报（{at}）没发给你：{f.get('why') or ''}。原文：{url}" if url
                         else f"· {symbol} 的财报（{at}）没发给你：{f.get('why') or ''}。")
        else:
            lines.append(f"· {symbol} 美东 {at}：{f.get('text') or ''}——按现在的设置应当提醒，但当时没有发出（收盘后用五分钟线重算发现）。")
    return "\n".join(lines)


def filtered_line(counts: dict, since: datetime) -> str:
    """The line code writes about the alerts the duty looked at and kept from him, from the window's start (Beijing); empty when none."""
    record, ignore = int(counts.get("record") or 0), int(counts.get("ignore") or 0)
    n = record + ignore
    if n == 0:
        return ""
    parts = [part for part, count in ((f"{record} 条只记下", record), (f"{ignore} 条不理会", ignore)) if count]
    start = since.astimezone(BEIJING).strftime("%m-%d %H:%M")
    return f"从 {start} 到现在，另有 {n} 条提醒我看过，判断不用打扰你（{'，'.join(parts)}），在后台「值班」里能看到。"


def _window_start(owner: str, now: datetime) -> datetime:
    """Where the brief's window starts: the newest done brief; else 24 hours before the owner's oldest brief row (so a failed day's rows
    are carried by the next brief); else 24 hours before ``now``."""
    last = duty_brief.last_done(owner)
    if last and last.get("created_at"):
        return datetime.fromisoformat(last["created_at"])
    oldest = duty_brief.earliest(owner)
    if oldest and oldest.get("created_at"):
        return datetime.fromisoformat(oldest["created_at"]) - WINDOW_DEFAULT
    return now - WINDOW_DEFAULT


def _first_line(text) -> str:
    stripped = text.strip() if isinstance(text, str) else ""
    return stripped.splitlines()[0] if stripped else ""


def fallback_text(kept: list[dict], held: list[dict]) -> str:
    """What is sent when the model could not write the brief: every kept alert's first line and every held message, as they are."""
    lines = [FALLBACK_HEAD]
    lines += [f"· {_first_line(item.get('text')) or item.get('symbol') or ''}" for item in kept]
    lines += [f"· {(item.get('message') or '').strip()}" for item in held]
    return "\n".join(lines)


async def _turn(owner: str, day: str, kept: list[dict], held: list[dict], facts: dict, turn_id: str, recorder: wake.Recorder, holder: dict) -> dict:
    """The model turn that writes the brief.  ``holder`` receives the hidden conversation's id as soon as it exists."""
    bot, context = await wake.duty_context(owner, holder)
    shown = [{key: value for key, value in item.items() if key != "id"} for item in held]     # the row id is the system's, not data for the model
    messages = prompt.build_brief_messages(context, kept, shown, facts)
    with model_usage.purpose("duty", owner_hash=owner, conversation_id=holder["conversation"], bot_id=bot.id, turn_id=turn_id, job=f"brief:{day}"):
        return await loop.run_wake(context, recorder.emit, messages, turn_id=turn_id, decide_tool=False)


async def _write(owner: str, day: str, kept: list[dict], held: list[dict], facts: dict) -> dict:
    """Run the model turn and store it.  Returns the body, why the fallback was used (or None), the turn id and the model calls."""
    turn_id = str(uuid.uuid4())
    recorder, holder, result, failure = wake.Recorder(), {}, None, None
    try:
        result = await asyncio.wait_for(_turn(owner, day, kept, held, facts, turn_id, recorder, holder), WALL_SECONDS)
    except TimeoutError:
        failure = f"超过 {WALL_SECONDS} 秒还没有写完"
    except Exception as exc:
        logger.warning("morning brief %s: the model turn failed: %s", day, wake._code(exc), exc_info=not hasattr(exc, "detail"))
        failure = f"模型这次没有写成：{wake._code(exc)}"
    answer = ((result or {}).get("answer") or "").strip()
    if result is not None and (result.get("reason") == "empty_answer" or not answer):
        failure, answer = "模型没有写出简报正文", ""
    reason = f"{failure}，改发原样列表。" if failure else None
    body = answer if not failure else fallback_text(kept, held)
    audit = (result or {}).get("audit") or {}
    if holder.get("conversation"):
        from ..agent_recall import TASK_POST_HEAD       # keeps the brief out of the past-conversation index, as wake turns are
        protocol = {"route": "K", **((result or {}).get("final_protocol") or {}),
                    "audit": audit or {"engine": "v2", "terminal_status": "failed", "model_calls": 0, "calls": []},
                    "citations": (result or {}).get("citations") or [], "unattended": True, "brief": True}
        try:
            await asyncio.to_thread(wake._store_turn, owner, holder["conversation"], turn_id, f"{TASK_POST_HEAD}早间简报 {day}", recorder, protocol,
                                    answer or reason or "没有结果。", result is None)
        except Exception:
            logger.exception("morning brief %s: the turn could not be stored", day)
    return {"body": body, "reason": reason, "turn_id": turn_id if holder.get("conversation") else None,
            "model_calls": int(audit.get("model_calls") or 0)}


async def _run(row_id: int, owner: str, day: str, current: str, now: datetime, since: datetime | None, began: float) -> dict:
    def ms() -> int:
        return round((time.monotonic() - began) * 1000)

    def finish(**fields) -> dict:
        return duty_brief.finish(row_id, ms=ms(), **fields)

    if current == "off":
        return await asyncio.to_thread(lambda: finish(outcome="skipped_off", reason=OFF))
    if since is None:
        since = await asyncio.to_thread(_window_start, owner, now)
    gathered = await asyncio.to_thread(gather, owner, since)
    kept, held, counts = gathered["kept"], gathered["held"], gathered["counts"]
    findings = gathered.get("findings") or []
    if findings:
        counts = {**counts, "missed": len(findings)}       # findings are content: a window with only findings is not skipped
    line = filtered_line(counts, since)
    missed = selfcheck_lines(findings)
    tail = "".join(f"\n\n{part}" for part in (missed, line) if part)
    if not any(counts.values()):
        return await asyncio.to_thread(lambda: finish(outcome="skipped", reason=NOTHING, counts=counts))
    if not kept and not held and not line and not missed:
        return await asyncio.to_thread(lambda: finish(outcome="skipped", reason=NOTHING_TO_SAY, counts=counts))
    fields: dict = {"counts": counts}
    if kept or held:
        written = await _write(owner, day, kept, held, facts(now, since, gathered["night_digest_sent"]))
        message = HEAD + written["body"] + tail        # the findings are the system's record: not given to the model
        fields.update(reason=written["reason"], turn_id=written["turn_id"], model_calls=written["model_calls"])
    else:
        message = HEAD + tail.removeprefix("\n\n")     # only code-written lines, no model call
    fields["message"] = message
    if current == "on":
        group, why = await asyncio.to_thread(lambda: wake._deliver(owner, message, source=SOURCE, cap=False))
        fields["delivery"] = why
        if group is not None:
            fields["delivery_group"] = group
        if why != "queued":
            # not sent: the window stays put, so the next brief carries these rows
            fields["reason"] = f"简报写好了但没能排进发件箱：{why}。夜里留下的事会由下一份简报补带。"
            return await asyncio.to_thread(lambda: finish(outcome="failed", **fields))
        if held:
            try:
                await asyncio.to_thread(duty_log.mark_briefed, [item["id"] for item in held])
            except Exception:       # the brief is already queued: it stays done, so tomorrow's does not send it again
                logger.exception("morning brief %s: the held rows could not be marked briefed", day)
                fields["reason"] = "简报已排进发件箱，但夜里留下的跟进没能标成已带出。"
    if gathered.get("selfcheck_ids"):
        try:            # carried: the next brief does not tell these again
            await asyncio.to_thread(duty_selfcheck.mark_briefed, gathered["selfcheck_ids"])
        except Exception:
            logger.exception("morning brief %s: the missed-alert checks could not be marked briefed", day)
    return await asyncio.to_thread(lambda: finish(outcome="done", **fields))


async def run_once(owner_hash: str, now: datetime, *, day: str | None = None, since: datetime | None = None) -> dict | None:
    """Write the day's brief if it is due and not written yet; returns its ``duty_brief`` row, or None (not due, or the day is taken).
    ``day`` and ``since`` are for the shadow replay: a day given skips the time check, a ``since`` given replaces the window's start.
    Never raises after the day is claimed: a failure finishes the row as ``failed``."""
    day = day or due_day(now)
    if day is None:
        return None
    if await asyncio.to_thread(duty_brief.get, owner_hash, day) is not None:
        return None        # already taken: skip the insert that would only conflict
    current = wake.mode()
    row_id = await asyncio.to_thread(duty_brief.claim, owner_hash, day, current)
    if row_id is None:
        return None
    began = time.monotonic()
    try:
        return await _run(row_id, owner_hash, day, current, now, since, began)
    except Exception as exc:
        logger.exception("morning brief %s failed", day)
        try:
            return await asyncio.to_thread(lambda: duty_brief.finish(row_id, outcome="failed", reason=f"这份简报没有完成：{type(exc).__name__}。",
                                                                     ms=round((time.monotonic() - began) * 1000)))
        except Exception:
            logger.exception("morning brief %s: the failure could not be logged", day)
            return None
