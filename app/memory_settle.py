"""The quarterly settle (stage 4c): code only, no model call.  Once a quarter (anchor dates, see ``memory_schedule``) it

* makes a confirmed guess that keeps showing up long-term (``settled_at``: the block and the page label it 「长期」),
* archives, with a reason, an inferred or guessed item his own words have not borne out for a long time, and a company view whose company he
  no longer holds, follows or mentions,

and posts one short change note.  Nothing is deleted: archived is kept and restorable on the memory page.  An explicit or manual item is his own
word and is never archived here.  A failed read of the ledger leaves the views alone (not knowing what he holds is not a reason to archive).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from . import agent_profile as profile
from . import owner_views
from .agent_chat_models import AgentBot, AgentConversation, AgentMessage, AgentProfileItem, AgentResearchQueue
from .agent_recall import owner_message_clause
from .company_directory import COMPANIES
from .database import SessionLocal

log = logging.getLogger(__name__)

SEEN_WITHIN_DAYS = 120        # a guess is long-term only if his words bore it out this recently ...
CONFIRMED_DAYS = 60           # ... and he confirmed it at least this long ago
DEFAULT_STALE_DAYS = 180
HEAD = "这一季的记忆整理："
TAIL = "归档的都还在记忆页，可以恢复。"
NOTICE = "每季整理：{summary}，详情在对话和记忆页。"
JOB_NAME = "每季整理记忆"
VIEW_REASON = "你已不持有、不在关注列表，也很久没提"
LIST_MAX = 10


def stale_days() -> int:
    try:
        return max(1, int(os.getenv("FINBOT_MEMORY_STALE_DAYS", "").strip() or DEFAULT_STALE_DAYS))
    except ValueError:
        return DEFAULT_STALE_DAYS


def _seen(row: AgentProfileItem) -> datetime | None:
    return row.last_seen_at or row.created_at


def _promote(db, owner_hash: str, now: datetime) -> list[str]:
    """Confirmed guesses (origin pattern, active) seen within 120 days and confirmed (``confirmed_at``) at least 60 days ago get ``settled_at``."""
    done = []
    rows = db.scalars(select(AgentProfileItem).where(AgentProfileItem.owner_hash == owner_hash, AgentProfileItem.origin == "pattern",
                                                     AgentProfileItem.status == "active", AgentProfileItem.settled_at.is_(None)))
    for row in rows:
        seen = _seen(row)
        if seen is None or row.confirmed_at is None:
            continue
        if seen >= now - timedelta(days=SEEN_WITHIN_DAYS) and row.confirmed_at <= now - timedelta(days=CONFIRMED_DAYS):
            db.execute(update(AgentProfileItem).where(AgentProfileItem.id == row.id)
                       .values(settled_at=now, updated_at=AgentProfileItem.updated_at).execution_options(synchronize_session=False))
            done.append(row.text)
    return done


def _expire(db, owner_hash: str, now: datetime, days: int) -> list[tuple[str, str]]:
    """Active inferred or guessed items not borne out for ``days`` days (a settled one: twice that) are archived with the date of the last time."""
    done = []
    rows = db.scalars(select(AgentProfileItem).where(AgentProfileItem.owner_hash == owner_hash, AgentProfileItem.status == "active",
                                                     AgentProfileItem.origin.in_(("inferred", "pattern"))))
    for row in rows:
        if row.origin in profile.OWNER_ORIGINS:      # never his own words (the query already leaves them out)
            continue
        seen = _seen(row)
        limit = days * (2 if row.settled_at else 1)
        if seen is None or seen >= now - timedelta(days=limit):
            continue
        reason = f"很久没在你的话里出现（最后一次 {seen.astimezone(UTC).month}月{seen.astimezone(UTC).day}日）"
        db.execute(update(AgentProfileItem).where(AgentProfileItem.id == row.id)
                   .values(status="archived", archived_at=now, archived_reason=reason, updated_at=AgentProfileItem.updated_at)
                   .execution_options(synchronize_session=False))
        done.append((row.text, reason))
    return done


def _held(owner_hash: str) -> set[str]:
    from . import portfolio
    with SessionLocal() as db:
        txns = [portfolio._row_to_txn(r) for r in portfolio.load_transactions(db, owner_hash)]
    return {s.upper() for s, p in portfolio.replay(txns).positions.items() if p.shares != 0}


def _queued(db, owner_hash: str) -> set[str]:
    row = db.get(AgentResearchQueue, owner_hash)
    return {str(s).upper() for s in (row.symbols if row else []) or [] if s}


def _focused(db, owner_hash: str) -> set[str]:
    found = set()
    for focus in db.scalars(select(AgentBot.focus).where(AgentBot.owner_hash == owner_hash)):
        for company in (focus or {}).get("companies") or []:
            if isinstance(company, dict) and company.get("symbol"):
                found.add(str(company["symbol"]).upper())
    return found


def _mentioned(db, owner_hash: str, symbols: set[str], since: datetime) -> set[str]:
    """Which of ``symbols`` his own messages since ``since`` name: the ticker, or a known name (a Latin name or ticker as a whole word, a Chinese
    name anywhere)."""
    if not symbols:
        return set()
    texts = [str(t or "").casefold() for t in db.scalars(
        select(AgentMessage.content).join(AgentConversation, AgentConversation.id == AgentMessage.conversation_id)
        .where(AgentConversation.owner_hash == owner_hash, owner_message_clause(), AgentMessage.created_at >= since))]
    body = "\n".join(texts)
    found = set()
    for symbol in symbols:
        for name in (symbol.casefold(), *(n.casefold() for n in COMPANIES.get(symbol, ()))):
            if name.isascii():
                hit = re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", body)
            else:
                hit = name in body
            if hit:
                found.add(symbol)
                break
    return found


def _plan_views(db, owner_hash: str, now: datetime, days: int) -> list[dict]:
    """The active views to archive.  Every read (ledger, queue, bot focus, his messages) happens here, before anything is written; a read
    that fails means no view is archived this quarter (not knowing what he holds is not a reason to archive)."""
    views = owner_views.all_current(owner_hash)
    if not views:
        return []
    try:
        keep = _held(owner_hash) | _queued(db, owner_hash) | _focused(db, owner_hash)
        keep |= _mentioned(db, owner_hash, {v["symbol"].upper() for v in views} - keep, now - timedelta(days=days))
    except Exception as exc:  # noqa: BLE001
        log.warning("quarterly settle: reading what he holds or follows failed (%s); views left alone", type(exc).__name__)
        return []
    return [v for v in views if v["symbol"].upper() not in keep]


def _archive_views(owner_hash: str, planned: list[dict], now: datetime) -> list[tuple[str, str]]:
    """Write the plan; what was actually archived is returned (a failure stops the rest but keeps what is done)."""
    done = []
    for view in planned:
        try:
            if owner_views.archive(owner_hash, view["id"], VIEW_REASON, at=now):
                done.append((f"{owner_views.display_name(view['symbol'])}的看法：{view['text']}", VIEW_REASON))
        except Exception as exc:  # noqa: BLE001
            log.warning("quarterly settle: archiving a view failed (%s)", type(exc).__name__)
            break
    return done


def _lines(items, with_reason: bool) -> list[str]:
    shown = [f"- {t}（{r}）" if with_reason else f"- {t}" for t, r in ((i, "") if isinstance(i, str) else i for i in items)][:LIST_MAX]
    if len(items) > LIST_MAX:
        shown.append(f"- 另有 {len(items) - LIST_MAX} 条")
    return shown


def _note(promoted: list[str], archived: list[tuple[str, str]]) -> str:
    parts = [HEAD]
    if promoted:
        parts += [f"转为长期 {len(promoted)} 条：", *_lines(promoted, False)]
    if archived:
        parts += [f"归档 {len(archived)} 条：", *_lines(archived, True)]
    parts.append(TAIL)
    return "\n".join(parts)


def run(owner_hash: str, now: datetime, last_run_at: datetime | None) -> dict:
    """One settle.  ``{"outcome": "done", "reason", promoted, archived, views_archived, posted}``; no model call."""
    days = stale_days()
    with SessionLocal() as db:
        planned = _plan_views(db, owner_hash, now, days)      # every read first
        profile._lock(db, owner_hash)
        promoted = _promote(db, owner_hash, now)
        expired = _expire(db, owner_hash, now, days)
        db.commit()
    view_expired = _archive_views(owner_hash, planned, now)   # the note below is made of what was actually written
    archived = expired + view_expired
    result = {"outcome": "done", "promoted": len(promoted), "archived": len(expired), "views_archived": len(view_expired), "posted": False}
    if not promoted and not archived:
        result["reason"] = "这一季没有要整理的。"
        return result
    summary = "、".join(x for x in (f"转为长期 {len(promoted)} 条" if promoted else "", f"归档 {len(archived)} 条" if archived else "") if x)
    result["reason"] = summary + "。"
    try:
        from .memory_review import _post
        result["posted"] = _post(owner_hash, _note(promoted, archived), now, what=JOB_NAME, marker="memory_settle", notice=NOTICE.format(summary=summary))
    except Exception as exc:  # noqa: BLE001 - the changes are made; the memory page shows them without the message
        log.warning("quarterly settle message not posted: %s", type(exc).__name__)
    return result
