"""「它眼中的你」: what the system keeps about the owner, gathered in one place for the memory page and for the export (stage 4e).

Read-only.  ``collect`` returns the parts the page lacks (counts, every version of his views with its look back, what he has asked to be watched,
the memory calendar, the profile text the default bot reads each turn); ``export`` adds every profile item and the conversation summaries and renders
the whole as JSON (for machines) or Markdown (for reading).  Nothing here changes a row, asks a model or hides an item: a part that cannot be read is
null and named, the rest still comes (one broken table never blanks the page), and the export says which part is missing.  The raw conversation is not
exported (the summaries are); a rejected guess keeps only a fingerprint, so only its count can be given.  No owner hash, session or channel setting is
read or written out.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from sqlalchemy import func, select

from . import memory_schedule, owner_views
from .agent_chat_models import (AgentBot, AgentConversation, AgentConversationSummary, AgentProfileItem, AgentResearchQueue, AgentTask, MemoryJob,
                                OwnerView)
from .database import SessionLocal

log = logging.getLogger(__name__)

SCHEMA = "finbot-memory-export/1"
SUMMARY_CAP = 2000
DEFAULT_RULES_NOTE = "另外，系统默认对你的持仓和研究队列盯价格异动、新公告（哨兵），这些默认规则现在还不能按你单独调整。"
NO_RAW_NOTE = "不含对话原文：原文在每条对话里，也在每夜的数据库备份里。"
FORMATS = {"json": ("json", "application/json; charset=utf-8"), "md": ("md", "text/markdown; charset=utf-8")}
PARTS = ("counts", "views", "watch", "jobs", "seen_block")


# --- the page's parts -----------------------------------------------------------------------------------------------------

def _plans(db, owner: str) -> list[dict]:
    """The owner's position plans that say anything (a price or some text), by symbol."""
    from .portfolio import load_plans
    found = []
    for symbol, plan in sorted(load_plans(db, owner).items()):
        if plan["plan_text"].strip() or any(plan[k] is not None for k in ("add_price", "stop_price", "target_price")):
            found.append({"symbol": symbol, "plan_text": plan["plan_text"], "add_price": plan["add_price"], "stop_price": plan["stop_price"],
                          "target_price": plan["target_price"], "updated_at": plan["updated_at"]})
    return found


def _routines(db, owner: str) -> list[dict]:
    from .agent_tasks import serialize_task
    rows = db.scalars(select(AgentTask).where(AgentTask.owner_hash == owner, AgentTask.kind == "alerts").order_by(AgentTask.created_at))
    found = []
    for row in rows:
        task = serialize_task(row)
        config = task["config"] if isinstance(task["config"], dict) else {}
        found.append({"id": task["id"], "name": task["name"], "enabled": task["enabled"], "scope": task["scope"], "symbols": task["symbols"],
                      "filings": bool(config.get("filings", True)), "news": bool(config.get("news", True)),
                      "price_lines": list(config.get("price_lines") or []), "next_run_at": task["next_run_at"], "bot_id": task["bot_id"]})
    return found


def _queue(db, owner: str) -> list[str] | None:
    """His research queue; None when he never saved one (as ``get_research_queue``)."""
    row = db.get(AgentResearchQueue, owner)
    return None if row is None else [str(s).upper() for s in (row.symbols or []) if s]


def _counts(db, owner: str) -> dict:
    by = {(origin, status): n for origin, status, n in db.execute(
        select(AgentProfileItem.origin, AgentProfileItem.status, func.count()).where(AgentProfileItem.owner_hash == owner)
        .group_by(AgentProfileItem.origin, AgentProfileItem.status))}

    def items(origin=None, status=None):
        return sum(n for (o, s), n in by.items() if (origin is None or o == origin) and (status is None or s == status))
    views_current = db.scalar(select(func.count()).select_from(OwnerView).where(OwnerView.owner_hash == owner, OwnerView.status == owner_views.ACTIVE))
    companies = db.scalar(select(func.count(OwnerView.symbol.distinct())).where(OwnerView.owner_hash == owner))
    watching = len(_plans(db, owner)) + sum(1 for r in _routines(db, owner) if r["enabled"]) + len(_queue(db, owner) or [])
    return {"said": items("explicit", "active"), "typed": items("manual", "active"), "inferred": items("inferred", "active"),
            "guesses_confirmed": items("pattern", "active"), "guesses_waiting": items(status="proposed"), "archived": items(status="archived"),
            "views_current": int(views_current or 0), "views_companies": int(companies or 0), "watch": watching}


def _watch(db, owner: str) -> dict:
    return {"plans": _plans(db, owner), "alert_routines": _routines(db, owner), "research_queue": _queue(db, owner),
            "default_rules_note": DEFAULT_RULES_NOTE}


def _jobs(owner: str) -> list[dict]:
    with SessionLocal() as db:
        rows = {r.job: r for r in db.scalars(select(MemoryJob).where(MemoryJob.owner_hash == owner))}
    order = [j for j in memory_schedule.JOBS if j in rows] + sorted(j for j in rows if j not in memory_schedule.JOBS)
    found = []
    for job in order:
        row = rows[job]
        due = memory_schedule.next_due(job, owner)
        entry = {"job": job, "title": memory_schedule.JOB_TITLES.get(job, job), "next_due": due.isoformat() if due else None,
                 "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None, "last_outcome": row.last_outcome, "last_reason": row.last_reason}
        if job == "monthly_review":
            since = memory_schedule.owner_messages_since(owner, row.last_run_at or row.created_at)
            entry["messages_until_early"] = max(0, memory_schedule.review_min_messages() - since)
        found.append(entry)
    return found


def _seen_block(owner: str) -> str | None:
    """The profile text a default-bot turn reads (``render_block`` with every bot's items), as it would be now.  Writes nothing: no ``touch_used``,
    and no default bot is made for the look (without one the block is the same, none of its items being the bot's own)."""
    from .agent_profile import render_block
    with SessionLocal() as db:
        bot = db.scalar(select(AgentBot.id).where(AgentBot.owner_hash == owner, AgentBot.is_default.is_(True)))
    return render_block(owner, str(bot) if bot else None, every_bot=True)[0]


def _part(errors: list, name: str, build):
    try:
        return build()
    except Exception as exc:  # noqa: BLE001 - one broken table never blanks the page
        log.warning("memory overview: reading %s failed (%s)", name, type(exc).__name__)
        errors.append(name)
        return None


def collect(owner_hash: str) -> dict:
    """The page's data; each part in its own try (null, and its name in ``errors``, when it cannot be read)."""
    errors: list[str] = []

    def in_session(function):
        def run():
            with SessionLocal() as db:
                return function(db, owner_hash)
        return run
    # The names are looked up when called, so a part replaced in a test or later is the one that runs.
    data = {"counts": _part(errors, "counts", in_session(lambda db, o: _counts(db, o))),
            "views": _part(errors, "views", lambda: owner_views.all_versions(owner_hash)),
            "watch": _part(errors, "watch", in_session(lambda db, o: _watch(db, o))),
            "jobs": _part(errors, "jobs", lambda: _jobs(owner_hash)),
            "seen_block": _part(errors, "seen_block", lambda: _seen_block(owner_hash))}
    data["errors"] = errors
    return data


# --- the export -----------------------------------------------------------------------------------------------------------

def _summaries(owner: str) -> tuple[list[dict], int]:
    """His conversation summaries (archived conversations too), oldest first; at most ``SUMMARY_CAP``, the newest kept.  Returns (rows, how many exist)."""
    with SessionLocal() as db:
        base = (select(AgentConversationSummary.conversation_id, AgentConversationSummary.seq, AgentConversationSummary.created_at,
                       AgentConversationSummary.content, AgentBot.name)
                .join(AgentConversation, AgentConversation.id == AgentConversationSummary.conversation_id)
                .outerjoin(AgentBot, AgentBot.id == AgentConversation.bot_id).where(AgentConversation.owner_hash == owner))
        total = db.scalar(select(func.count()).select_from(AgentConversationSummary)
                          .join(AgentConversation, AgentConversation.id == AgentConversationSummary.conversation_id)
                          .where(AgentConversation.owner_hash == owner)) or 0
        rows = db.execute(base.order_by(AgentConversationSummary.created_at.desc(), AgentConversationSummary.seq.desc()).limit(SUMMARY_CAP)).all()
    found = [{"conversation_id": str(cid), "bot_name": name, "seq": seq, "created_at": at.isoformat() if at else None, "content": content}
             for cid, seq, at, content, name in reversed(rows)]
    return found, int(total)


def _rejected_count(owner: str) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(AgentProfileItem)
                             .where(AgentProfileItem.owner_hash == owner, AgentProfileItem.status == "rejected")) or 0)


def build(owner_hash: str, now: datetime | None = None) -> dict:
    """The export document (what ``export`` writes as JSON)."""
    from .agent_profile import list_items
    now = now or datetime.now(UTC)
    data = collect(owner_hash)
    summaries, total = _summaries(owner_hash)
    rejected = _rejected_count(owner_hash)
    notes = [NO_RAW_NOTE, f"被你否掉的推测只留了一个指纹，没有文字，共 {rejected} 条。"]
    if total > len(summaries):
        notes.append(f"对话摘要只导出了最近 {SUMMARY_CAP} 段")
    if data["errors"]:
        notes.append("导出不完整：这几部分这次没能读出，在文件里是空的：" + "、".join(data["errors"]))
    return {"schema": SCHEMA, "exported_at": now.isoformat(), "counts": data["counts"], "profile_items": list_items(owner_hash, include_archived=True),
            "rejected_count": rejected, "views": data["views"], "watch": data["watch"], "jobs": data["jobs"], "seen_block": data["seen_block"],
            "conversation_summaries": summaries, "notes": notes}


def export(owner_hash: str, fmt: str, now: datetime | None = None) -> tuple[bytes, str, str]:
    """``(content, filename, media_type)`` of the owner's memory as ``json`` or ``md``; ``ValueError("invalid_format")`` for anything else."""
    if fmt not in FORMATS:
        raise ValueError("invalid_format")
    now = now or datetime.now(UTC)
    doc = build(owner_hash, now)
    extension, media_type = FORMATS[fmt]
    text = json.dumps(doc, ensure_ascii=False, indent=2) if fmt == "json" else render_markdown(doc)
    return text.encode("utf-8"), f"finbot-memory-{now.astimezone(UTC):%Y%m%d}.{extension}", media_type


# --- Markdown ---------------------------------------------------------------------------------------------------------------

NONE_LINE = "（没有）"
MISSING_LINE = "（这一部分这次没能读出）"
ITEM_SECTIONS = (("你说过的", "explicit", "active"), ("你在记忆页写的", "manual", "active"), ("它推断的", "inferred", "active"),
                 ("你确认的推测", "pattern", "active"), ("待你确认的推测", None, "proposed"), ("已归档", None, "archived"))
COUNT_LABELS = (("said", "你明说的"), ("typed", "你在记忆页写的"), ("inferred", "它推断的"), ("guesses_confirmed", "你确认过的推测"),
                ("guesses_waiting", "等你确认的推测"), ("archived", "已归档"), ("views_current", "当前的看法"), ("views_companies", "有过看法的公司"),
                ("watch", "盯防项"))
OUTCOMES = {"done": "完成", "skipped": "跳过", "failed": "出错"}


def _day(iso) -> str:
    return str(iso)[:10] if iso else "—"


def _layer(item: dict) -> str:
    return f"bot「{item.get('bot_name') or '已删除的 bot'}」" if item.get("bot_id") else "全局"


def _item_line(item: dict) -> str:
    kind = {"preference": "偏好", "about_me": "关于我", "instruction": "长期指令"}.get(item.get("kind"), item.get("kind") or "")
    bits = [_layer(item), kind, f"记于 {_day(item.get('created_at'))}", f"最近一次提到 {_day(item.get('last_seen_at'))}"]
    if item.get("confirmed_at"):
        bits.append(f"你确认于 {_day(item['confirmed_at'])}")
    if item.get("settled_label"):
        bits.append(item["settled_label"])
    if item.get("status") == "archived":
        bits.append(f"归档于 {_day(item.get('archived_at'))}" + (f"，原因：{item['archived_reason']}" if item.get("archived_reason") else ""))
    line = f"- {item['text']}（{'；'.join(bits)}）"
    quote = (item.get("quote") or "").strip()
    if quote and quote != item["text"] and not item.get("examples"):
        line += f"\n  - 原话：「{quote}」"
    for example in item.get("examples") or []:
        if isinstance(example, dict) and example.get("quote"):
            line += f"\n  - 例子：「{example['quote']}」" + (f"（{_day(example['on'])}）" if example.get("on") else "")
    return line


def _items_section(items: list[dict], origin, status) -> list[str]:
    chosen = [i for i in items if i.get("status") == status and (origin is None or i.get("origin") == origin)]
    return [_item_line(i) for i in chosen] or [NONE_LINE]


def _basis_text(basis) -> str:
    if not isinstance(basis, dict):
        return ""
    bits = []
    def close(point):       # the stored shape is {date, close} (4d); a bare number is read too
        value = point.get("close") if isinstance(point, dict) else point
        return f"{value:g}" if isinstance(value, (int, float)) else "—"
    if basis.get("price_then") is not None or basis.get("price_now") is not None:
        move = f"（{basis['change_pct']:+g}%）" if isinstance(basis.get("change_pct"), (int, float)) else ""
        bits.append(f"股价 {close(basis.get('price_then'))} → {close(basis.get('price_now'))}{move}")
    if basis.get("quarter_label"):
        bits.append(f"最新一季 {basis['quarter_label']}")
    return "；".join(bits)


def _version_lines(version: dict) -> list[str]:
    state = "当前" if version.get("status") == owner_views.ACTIVE else (version.get("status_label") or version.get("status") or "")
    where = "在记忆页写的" if not version.get("conversation_id") else "在对话里说的"
    span = f"{_day(version.get('created_at'))} 起" + (f"，{_day(version['ended_at'])} 止" if version.get("ended_at") else "")
    head = f"- 【{state}】{version['text']}（{span}；{where}"
    if version.get("archived_reason"):
        head += f"；归档原因：{version['archived_reason']}"
    lines = [head + "）", f"  - 他的原话：「{version.get('quote') or ''}」"]
    review = version.get("review")
    if review:
        line = f"  - 回头看（{_day(review.get('created_at'))}）：{review.get('verdict_label') or review.get('verdict')}——{review.get('text')}"
        lines.append(line)
        basis = _basis_text(review.get("basis"))
        if basis:
            lines.append(f"    - 依据：{basis}")
        if review.get("unmatched_figures"):
            lines.append("    - 注：它写的这些数字不在系统给它的资料里：" + "、".join(review["unmatched_figures"]))
    return lines


def _price_line(line: dict) -> str:
    sides = [f"{'高于' if side == 'above' else '低于'} {line[side]:g}" for side in ("above", "below") if line.get(side) is not None]
    return f"{line.get('symbol', '')} {' / '.join(sides)}"


def _watch_lines(watch) -> list[str]:
    if watch is None:
        return [MISSING_LINE]
    lines = ["### 持仓计划"]
    for plan in watch.get("plans") or []:
        parts = [f"{label} {plan[key]}" for key, label in (("add_price", "补仓"), ("stop_price", "止损"), ("target_price", "目标")) if plan.get(key) is not None]
        if plan.get("plan_text"):
            parts.append(f"文字计划：{plan['plan_text']}")
        lines.append(f"- {plan['symbol']}：{'；'.join(parts)}")
    lines += [NONE_LINE] if not watch.get("plans") else []
    lines += ["", "### 盯盘任务"]
    for routine in watch.get("alert_routines") or []:
        what = [f"公告{'：看' if routine.get('filings') else '：不看'}", f"新闻{'：看' if routine.get('news') else '：不看'}"]
        if routine.get("price_lines"):
            what.append("价位线：" + "、".join(_price_line(p) for p in routine["price_lines"]))
        scope = "、".join(routine.get("symbols") or []) if routine.get("scope") == "symbols" else "研究队列"
        lines.append(f"- {routine['name']}（范围：{scope}；{'；'.join(what)}；下次运行 {_day(routine.get('next_run_at'))}" + ("" if routine.get("enabled") else "；已暂停") + "）")
    lines += [NONE_LINE] if not watch.get("alert_routines") else []
    queue = watch.get("research_queue")
    lines += ["", "### 研究队列", ("、".join(queue) if queue else NONE_LINE) if queue is not None else "（还没存过研究队列）"]
    if watch.get("default_rules_note"):
        lines += ["", watch["default_rules_note"]]
    return lines


def _job_lines(jobs) -> list[str]:
    if jobs is None:
        return [MISSING_LINE]
    lines = []
    for job in jobs:
        last = OUTCOMES.get(job.get("last_outcome"), "")
        line = f"- {job.get('title') or job['job']}：下次 {_day(job.get('next_due'))}"
        if job.get("last_run_at") or last:
            line += f"；上次 {_day(job.get('last_run_at'))}" + (f" {last}" if last else "") + (f"（{job['last_reason']}）" if job.get("last_reason") else "")
        if job.get("messages_until_early") is not None:
            line += f"；再发 {job['messages_until_early']} 条消息会提前"
        lines.append(line)
    return lines or [NONE_LINE]


def _fence(text: str) -> str:
    longest = max([len(run) for run in re.findall(r"`+", text)] or [0])
    return "`" * max(3, longest + 1)


_ROLLING_TITLES = {"goals": "目标", "conclusions": "结论", "open": "未办完", "preferences": "偏好", "numbers": "关键数字"}


def _summary_lines(content) -> list[str]:
    """A summary as readable lines: a structured (rolling) summary becomes its lists under plain headings, without the source markers that only
    the model uses; a free-text summary stays as it is."""
    from .agent_context import ROLLING_LISTS, parse_rolling
    rolling = parse_rolling(content)
    if rolling is None:
        return str(content or "").splitlines()
    lines: list[str] = []
    for key in ROLLING_LISTS:
        items = [item.get("text", "") if isinstance(item, dict) else str(item) for item in rolling.get(key) or []]
        items = [item for item in items if item]
        if items:
            lines += [f"**{_ROLLING_TITLES[key]}**"] + [f"- {item}" for item in items]
    return lines


def render_markdown(doc: dict) -> str:
    """The export document as Markdown, for reading.  Pure (no database).  Every section is always there; an empty one says so."""
    out = [f"# 它眼中的你（导出于 {_day(doc.get('exported_at'))}）", "", "## 概览", ""]
    counts = doc.get("counts")
    if counts is None:
        out.append(MISSING_LINE)
    else:
        out += [f"- {label}：{counts.get(key, 0)}" for key, label in COUNT_LABELS]
    items = doc.get("profile_items") or []
    placed = set()
    for title, origin, status in ITEM_SECTIONS:
        out += ["", f"## {title}", ""] + _items_section(items, origin, status)
        placed |= {id(i) for i in items if i.get("status") == status and (origin is None or i.get("origin") == origin)}
    left = [i for i in items if id(i) not in placed]
    if left:                                   # an item of a status or origin this export does not know is still shown
        out += ["", "## 其他记忆", ""] + [_item_line(i) for i in left]
    out += ["", "## 你对公司的看法", ""]
    views = doc.get("views")
    if views is None:
        out.append(MISSING_LINE)
    elif not views:
        out.append(NONE_LINE)
    for group in views or []:
        out += [f"### {group.get('name') or group['symbol']}（{group['symbol']}）"]
        for version in group.get("versions") or []:
            out += _version_lines(version)
        out.append("")
    if out[-1] == "":
        out.pop()
    out += ["", "## 盯防", ""] + _watch_lines(doc.get("watch"))
    out += ["", "## 记忆整理日程", ""] + _job_lines(doc.get("jobs"))
    out += ["", "## 它每轮读到的画像", ""]
    block = doc.get("seen_block")
    if block:
        fence = _fence(block)
        out += [fence + "text", block, fence]
    else:
        out.append(NONE_LINE)
    out += ["", "## 对话摘要", ""]
    summaries = doc.get("conversation_summaries") or []
    for summary in summaries:
        out += [f"### {summary.get('bot_name') or '（没有 bot）'} · 第 {summary.get('seq')} 段 · {_day(summary.get('created_at'))}", ""]
        out += ["> " + line for line in _summary_lines(summary.get("content")) or [""]]
        out.append("")
    if not summaries:
        out.append(NONE_LINE)
    elif out[-1] == "":
        out.pop()
    out += ["", "## 说明", ""] + [f"- {note}" for note in doc.get("notes") or []]
    return "\n".join(out) + "\n"
