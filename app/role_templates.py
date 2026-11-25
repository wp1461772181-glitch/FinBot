"""Role templates (stage 4f): 「短线」「定投」「基金经理」 as a starting memory and starting settings, nothing more.

A template is text: memory lines, routine briefs and recipes (skills).  Applying one writes ordinary rows through the services the owner's
own pages use (``agent_profile.add_item``, ``agent_skills.create_skill``, ``agent_tasks.create_task``, ``agent_bots.update_bot``); the
kernel, the prompt and the duty wake read the result exactly as if he had typed it.  No code path outside this module knows a template id
(``tests/test_role_templates.py`` greps ``app/`` for them), and a template adds no guard, filter or required format to any answer.

Applying never archives, overwrites or evicts anything the owner has: a duplicate is reused and reported, a full memory layer refuses the
memory part with a reason.  ``undo`` takes back only what the application recorded and is still there.  No model call happens here.
"""
from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from . import agent_bots, agent_profile, agent_skills, agent_tasks
from .agent_chat_models import AgentBot, AgentSkill, AgentTask, RoleTemplateApplication
from .database import SessionLocal

TEMPLATES: dict[str, dict] = {
    "short_term": {
        "label": "短线",
        "blurb": "看日内和几天内的走势：回答先给结论和价位，急涨急跌也告诉你，开盘前给一份速览。",
        "memory": [
            {"key": "st_about", "kind": "about_me", "text": "我主要做短线，关注日内和几天内的走势，持有时间短。"},
            {"key": "st_conclusion_first", "kind": "instruction", "text": "回答先给结论和关键价位，再讲原因；提到价格都写明是几点的数据。"},
            {"key": "st_fast_moves", "kind": "instruction", "text": "我的持仓盘中出现急涨急跌（5 分钟、15 分钟这种），也算值得告诉我的事。"},
            {"key": "st_why_moving", "kind": "instruction", "text": "说异动时先讲是它自己的事，还是大盘、板块一起动，再讲原因；查不到原因就直说没查到。"},
            {"key": "st_news_impact", "kind": "preference", "text": "新闻和公告先说对股价的直接影响，背景放后面。"},
        ],
        "briefs": [
            {"key": "st_premarket", "name": "盘前速览", "schedule_kind": "weekdays", "schedule_time": "09:00", "timezone": "America/New_York",
             "skill_key": "st_skill_premarket",
             "instruction": "开盘前给我一份速览：持仓和研究队列里，隔夜有公告、新闻或盘前涨跌明显的，每只一句话——发生了什么、盘前涨跌多少、离我设的补仓价/止损价/目标价还有多远。没有值得说的，就只回一句『今天盘前没有要特别注意的』。"},
        ],
        "skills": [
            {"key": "st_skill_premarket", "name": "盘前速览",
             "description": "开盘前把持仓和研究队列过一遍：隔夜公告、新闻、盘前涨跌和离计划价位的距离。",
             "body": ("1. 用 query_portfolio 读持仓和计划价位，用 query_research_queue 读研究队列。\n"
                      "2. 用 query_market_quote / query_stock_prices 看每只的最新价和相对昨收的涨跌，写明数据时间。\n"
                      "3. 用 query_sec_filings 和 search_configured_news 找隔夜的公告和新闻；不够再用 web_research。\n"
                      "4. 离计划价位的距离用 calculate 算。\n"
                      "5. 只写有事的那几只，每只一句；都没事就说没事。"),
             "output_template": "**今天要注意的**（每只：公司 · 发生了什么 · 盘前涨跌（时间）· 离计划价位）\n**没事的**（一行列出）",
             "allowed_tools": ["query_portfolio", "query_research_queue", "query_market_quote", "query_stock_prices", "query_sec_filings",
                               "search_configured_news", "web_research", "calculate"]},
            {"key": "st_skill_why", "name": "异动归因",
             "description": "一只股票为什么大涨大跌：先看公告和新闻，再看大盘和同行。",
             "body": ("1. 用 query_market_quote / query_stock_prices 确认涨跌幅和时间。\n"
                      "2. 用 query_sec_filings 看最近的官方公告，用 search_configured_news 看新闻；不够再用 web_research，必要时 search_x（标明是社交平台内容）。\n"
                      "3. 用 query_stock_prices 看大盘和一两家同行同一时间的涨跌，分清是它自己的事还是一起动。\n"
                      "4. 写原因时带出处；查不到就直说没查到。"),
             "output_template": "**涨跌**（多少，几点）\n**原因**（带出处；没查到就写没查到）\n**是它自己还是一起动**",
             "allowed_tools": ["query_market_quote", "query_stock_prices", "query_sec_filings", "search_configured_news", "web_research",
                               "search_x", "query_alerts"]},
        ],
        "usual": ["st_skill_premarket", "st_skill_why", "新闻摘要"],
    },
    "dca": {
        "label": "定投",
        "blurb": "长期按节奏买入、不择时：日常涨跌不打扰你，每月复盘一次持仓和你的判断。",
        "memory": [
            {"key": "dca_about", "kind": "about_me", "text": "我做长期定投，按固定节奏买入，不做择时。"},
            {"key": "dca_quiet", "kind": "instruction", "text": "日常涨跌不用特意告诉我；持仓公司的重要公告、财报，或明显超出平时波动的大跌，才值得说。"},
            {"key": "dca_no_timing", "kind": "instruction", "text": "谈买卖时从长期基本面和我的定投计划出发，不给短线择时的建议。"},
            {"key": "dca_reading", "kind": "preference", "text": "财报先看收入、利润和现金流的长期趋势，还有分红和回购；同比优先于环比。"},
        ],
        "briefs": [
            {"key": "dca_monthly", "name": "每月定投复盘", "schedule_kind": "every", "every_value": 30, "every_unit": "days",
             "schedule_time": "10:00", "timezone": "Asia/Shanghai", "skill_key": "dca_skill_review",
             "instruction": "按『定投复盘』的步骤给我一份月度复盘：每只持仓的成本、现价、浮盈亏和占比，和上次比的变化；这段时间持仓公司有没有改变长期判断的事（财报、指引、重要公告）；我记下的看法现在还成立吗。不给择时建议。"},
        ],
        "skills": [
            {"key": "dca_skill_review", "name": "定投复盘",
             "description": "定期看一遍持仓：成本、占比、长期基本面的变化和你当初的判断。",
             "body": ("1. 用 query_portfolio / query_holdings_overview 读每只持仓的成本、现价、浮盈亏和占比。\n"
                      "2. 用 query_financials 看最近一期和去年同期的收入、利润、经营现金流；需要的比率用 calculate 算。\n"
                      "3. 用 query_sec_filings 看这段时间的重要公告和指引。\n"
                      "4. 对照系统里记下的他的看法，说哪些依据还在、哪些变了；只讲依据，不给择时建议。"),
             "output_template": "**持仓一览**（表格：公司 / 成本 / 现价 / 浮盈亏 / 占比）\n**基本面有没有变**\n**你的看法还成立吗**",
             "allowed_tools": ["query_portfolio", "query_holdings_overview", "query_financials", "query_sec_filings", "query_stock_prices",
                               "calculate"]},
        ],
        "usual": ["dca_skill_review", "财报速读"],
    },
    "fund_manager": {
        "label": "基金经理",
        "blurb": "按组合来管：盯集中度和回撤，收盘给一份组合日报，判断都写依据和反方。",
        "memory": [
            {"key": "fm_about", "kind": "about_me", "text": "我按组合来管理，关心整体风险、集中度和相对大盘的表现。"},
            {"key": "fm_limits", "kind": "instruction", "text": "单只持仓占总资产超过 25%，或组合一天跌超过 3%，值得告诉我。"},
            {"key": "fm_position_context", "kind": "instruction", "text": "谈个股时顺带说它在组合里的占比和对组合的影响。"},
            {"key": "fm_both_sides", "kind": "instruction", "text": "每个判断写清依据，也写反方的看法。"},
            {"key": "fm_format", "kind": "preference", "text": "数字尽量用表格，金额用美元，比例保留一位小数。"},
        ],
        "briefs": [
            {"key": "fm_daily", "name": "收盘组合日报", "schedule_kind": "weekdays", "schedule_time": "16:30", "timezone": "America/New_York",
             "instruction": "收盘后给我一份组合日报：总资产和当日涨跌，贡献最大和拖累最大的各三只，占比的变化，今天持仓公司的公告和重要新闻；超过我说过的集中度或回撤线的单独标出来。"},
            {"key": "fm_weekly", "name": "每周组合体检", "schedule_kind": "every", "every_value": 7, "every_unit": "days",
             "schedule_time": "10:00", "timezone": "Asia/Shanghai", "skill_key": "fm_skill_check",
             "instruction": "按『组合体检』的步骤做一次周度体检，重点写这一周变了什么。"},
        ],
        "skills": [
            {"key": "fm_skill_check", "name": "组合体检",
             "description": "看组合整体：集中度、各只的贡献、相对大盘的表现和主要风险。",
             "body": ("1. 用 query_portfolio / query_holdings_overview 读持仓、占比和总资产。\n"
                      "2. 用 query_stock_prices 看各只和大盘（如 SPY）同一段时间的涨跌；贡献和相对表现用 calculate 算。\n"
                      "3. 标出占比最高的几只和超过他说过的上限的。\n"
                      "4. 用 query_financials / query_sec_filings 看重仓公司最近有没有基本面变化。\n"
                      "5. 每条判断写依据和反方看法。"),
             "output_template": "**组合概况**（总资产、期间涨跌、相对大盘）\n**集中度**（表格：公司 / 占比 / 期间贡献）\n**要留意的风险**（每条带依据和反方）",
             "allowed_tools": ["query_portfolio", "query_holdings_overview", "query_stock_prices", "query_market_quote", "query_financials",
                               "query_sec_filings", "calculate"]},
        ],
        "usual": ["fm_skill_check", "同行对比", "财报速读"],
    },
}

# The fixed sentences the page and the card show (statements about what a template reaches today, not switches).  Nothing here reads or
# writes the environment; the duty sentence depends only on the mode the wake loop itself reports.
NOTE_READ = "盯防类的几条会在每次回答和值班判断时读到。"
NOTE_DUTY_RECORDS = "值班现在只记录、不主动发消息（要打开请告诉我），所以这几条暂时只影响回答。"
NOTE_SENTINEL = "价格异动的默认提醒（哨兵）这一版不随模板改变。"
NOTE_BRIEF_COST = "每条简报每次运行会调用一次模型，记在用量里；不想要可以不勾，或之后在例行任务里暂停。"
NOTE_TELL_ME = "持仓、计划价位和你对公司的看法，还要在对话里慢慢告诉它。"
NOTES = (NOTE_READ, NOTE_DUTY_RECORDS, NOTE_SENTINEL, NOTE_BRIEF_COST, NOTE_TELL_ME)

MEMORY_FULL = "memory_full"
GLOBAL_TARGET = "global"


def notes(duty_mode: str | None = None) -> list[str]:
    """The fixed sentences, with the duty one dropped once the duty loop really messages (mode ``on``).  ``duty_mode`` None reads it live."""
    if duty_mode is None:
        from .kernel import wake
        duty_mode = wake.mode()
    return [text for text in NOTES if not (text == NOTE_DUTY_RECORDS and duty_mode == "on")]


def templates(duty_mode: str | None = None) -> list[dict]:
    """Every template as the page shows it: a copy (the caller may change it), with its id and the notes."""
    listed = notes(duty_mode)
    return [{"id": template_id, **copy.deepcopy(template), "notes": list(listed)} for template_id, template in TEMPLATES.items()]


def brief_fields(brief: dict, *, skill_id: str | None = None, bot_id: str | None = None) -> dict:
    """The ``create_task`` fields of one brief.  ``skill_id`` and ``bot_id`` are left out when not known, so the same call also feeds
    ``preview_task``."""
    fields = {"kind": "brief", "name": brief["name"], "schedule_kind": brief["schedule_kind"], "schedule_time": brief["schedule_time"],
              "timezone": brief["timezone"], "instruction": brief["instruction"], "scope": "research_queue", "channel": "inbox",
              "enabled": True}
    if brief["schedule_kind"] == "every":
        fields["every_value"], fields["every_unit"] = brief["every_value"], brief["every_unit"]
    if skill_id:
        fields["skill_id"] = skill_id
    if bot_id:
        fields["bot_id"] = bot_id
    return fields


# ---- preview, apply, undo -----------------------------------------------------------------------------------------------------

USUAL_MAX = 20
PART_ORDER = ("skill", "memory", "brief", "usual")
REUSE_SKILL = "已有同名技能，沿用你的"
REUSE_MEMORY = "已有，沿用"
REUSE_USUAL = "已在常用技能里"
TASK_NAME_TAKEN = "已有同名任务"
GONE = "已经不在了"
ZONE_NAMES = {"America/New_York": "美东时间", "Asia/Shanghai": "北京时间"}
EVERY_UNITS = {"days": "天", "hours": "小时", "weeks": "周"}
_NEW = "new:"          # a skill this application will create, before it has an id


class RoleTemplateError(ValueError):
    """A short code the routes show: unknown_template, unknown_bot, unknown_leave_out, application_not_found, already_undone."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _template(template_id) -> dict:
    template = TEMPLATES.get(str(template_id or ""))
    if template is None:
        raise RoleTemplateError("unknown_template")
    return template


def _left_out(template: dict, leave_out) -> set[str]:
    """The keys he unticked.  A key the template does not have is refused, not ignored (a typo must not write what he meant to leave out)."""
    valid = ({m["key"] for m in template["memory"]} | {b["key"] for b in template["briefs"]} | {s["key"] for s in template["skills"]}
             | set(template["usual"]))
    left = [str(key) for key in (leave_out or [])]
    if any(key not in valid for key in left):
        raise RoleTemplateError("unknown_leave_out")
    return set(left)


def _default_bot(owner_hash: str) -> dict | None:
    """His 「助理」 as it is now, or None when it has not been made yet (a preview never makes it)."""
    with SessionLocal() as db:
        row = db.scalars(select(AgentBot).where(AgentBot.owner_hash == owner_hash, AgentBot.is_default.is_(True))).first()
        return {"id": str(row.id), "name": row.name, "skills": list(row.skills or [])} if row else None


def _target(owner_hash: str, bot_id, *, create: bool) -> dict:
    """Where it lands: the global memory layer and 「助理」 (``bot_id`` None), or one of his bots' own layer, tasks and usual skills."""
    if bot_id in (None, ""):
        if create:
            agent_bots.ensure_default_bot(owner_hash)
        found = _default_bot(owner_hash)
        return {"scope": "global", "layer": None, "bot_id": found["id"] if found else None, "usual": list(found["skills"]) if found else [],
                "bot_name": found["name"] if found else agent_bots.DEFAULT_NAME}
    try:
        uuid.UUID(str(bot_id))
    except (TypeError, ValueError) as exc:
        raise RoleTemplateError("unknown_bot") from exc
    bot = agent_bots.get_bot(owner_hash, bot_id)
    if bot is None:
        raise RoleTemplateError("unknown_bot")
    return {"scope": "bot", "layer": bot["id"], "bot_id": bot["id"], "bot_name": bot["name"], "usual": list(bot.get("skills") or [])}


def _when(brief: dict) -> str:
    """The schedule in plain words, with the zone it is set in."""
    zone, at, kind = ZONE_NAMES.get(brief["timezone"], brief["timezone"]), brief["schedule_time"], brief["schedule_kind"]
    if kind == "weekdays":
        head = f"工作日 {at}"
    elif kind == "daily":
        head = f"每天 {at}"
    elif kind == "every":
        head = f"每 {brief['every_value']} {EVERY_UNITS.get(brief['every_unit'], brief['every_unit'])}，{at}"
    else:
        head = at
    return f"{head}（{zone}）"


def _skill_entries(owner_hash: str, template: dict, left: set[str]) -> tuple[list[dict], dict, list[dict]]:
    """The template's skills: created, reused (he already has one of that name, active) or skipped.  Returns (entries, resolved, all skills)."""
    skills = agent_skills.list_skills(owner_hash)
    by_name = {s["name"]: s for s in skills}
    mine = sum(1 for s in skills if not s["builtin"])
    entries, resolved = [], {}
    for spec in template["skills"]:
        if spec["key"] in left:
            resolved[spec["key"]] = None
            continue
        base = {"part": "skill", "key": spec["key"], "label": spec["name"], "name": spec["name"]}
        row = by_name.get(spec["name"])
        if row is not None and row["status"] == "active" and row.get("enabled", True):
            entries.append({**base, "status": "reuse", "id": row["id"], "reason": REUSE_SKILL})
            resolved[spec["key"]] = row["id"]
        elif row is not None:
            entries.append({**base, "status": "skip", "code": "name_taken", "reason": "已有同名技能（不是启用中的），没有创建"})
            resolved[spec["key"]] = None
        elif mine >= agent_skills.MAX_SKILLS:
            entries.append({**base, "status": "skip", "code": "too_many_skills", "reason": f"你的技能已满 {agent_skills.MAX_SKILLS} 个，没有创建"})
            resolved[spec["key"]] = None
        else:
            mine += 1
            entries.append({**base, "status": "create", "spec": spec})
            resolved[spec["key"]] = _NEW + spec["key"]
    return entries, resolved, skills


def _memory_entries(owner_hash: str, template: dict, left: set[str], layer) -> list[dict]:
    """The template's memory lines: reused when the layer already has the same line (same text and kind, active), the rest created or, when
    they would not fit under the layer's limit, ALL refused together (nothing of his is archived to make room)."""
    active = [i for i in agent_profile.list_items(owner_hash, include_archived=False) if i["status"] == "active" and i["bot_id"] == layer]
    plain = agent_profile._plain
    entries = []
    for line in template["memory"]:
        if line["key"] in left:
            continue
        base = {"part": "memory", "key": line["key"], "label": line["text"], "kind": line["kind"], "text": line["text"]}
        same = any(plain(i["text"]) == plain(line["text"]) and i["kind"] == line["kind"] for i in active)
        entries.append({**base, "status": "reuse", "reason": REUSE_MEMORY} if same else {**base, "status": "create"})
    fresh = [e for e in entries if e["status"] == "create"]
    if fresh and len(active) + len(fresh) > agent_profile.MAX_ACTIVE_ITEMS:
        reason = f"这一层记忆已有 {len(active)} 条，再加 {len(fresh)} 条会超过 {agent_profile.MAX_ACTIVE_ITEMS} 条；先删几条或少勾几条"
        for entry in fresh:
            entry.update(status="skip", code=MEMORY_FULL, reason=reason)
    return entries


def _brief_entries(owner_hash: str, template: dict, left: set[str], target: dict, resolved: dict, skill_names: dict) -> list[dict]:
    tasks = agent_tasks.list_tasks(owner_hash)
    names = {t["name"] for t in tasks if target["bot_id"] and str(t.get("bot_id")) == str(target["bot_id"])}
    total = len(tasks)
    entries = []
    for brief in template["briefs"]:
        if brief["key"] in left:
            continue
        skill_key = brief.get("skill_key")
        has_skill = bool(skill_key and resolved.get(skill_key))
        base = {"part": "brief", "key": brief["key"], "label": brief["name"], "name": brief["name"], "when": _when(brief),
                "instruction": brief["instruction"], "skill_key": skill_key if has_skill else None,
                "skill_name": skill_names.get(skill_key) if has_skill else None}
        if brief["name"] in names:
            entries.append({**base, "status": "skip", "code": "name_taken", "reason": TASK_NAME_TAKEN})
        elif total >= agent_tasks.MAX_TASKS:
            entries.append({**base, "status": "skip", "code": "too_many_tasks", "reason": f"例行任务已满 {agent_tasks.MAX_TASKS} 个，没有创建"})
        else:
            total += 1
            names.add(brief["name"])
            entries.append({**base, "status": "create"})
    return entries


def _usual_entries(template: dict, left: set[str], target: dict, resolved: dict, skills: list[dict]) -> list[dict]:
    """The template's usual skills, appended after the ones the bot already has (up to 20); a built-in is named by its name."""
    builtin = {s["name"]: s["id"] for s in skills if s["builtin"] and s["status"] == "active"}
    current, planned, entries = list(target["usual"]), list(target["usual"]), []
    for key in template["usual"]:
        if key in left:
            continue
        if key in resolved:
            skill_id = resolved[key]
            if not skill_id:
                continue            # that skill was left out or not made: its own entry says why
            label = next((s["name"] for s in template["skills"] if s["key"] == key), key)
        else:
            skill_id, label = builtin.get(key), key
            if not skill_id:
                continue
        base = {"part": "usual", "key": key, "label": label, "skill_id": skill_id}
        if skill_id in current:
            entries.append({**base, "status": "reuse", "reason": REUSE_USUAL})
        elif len(planned) >= USUAL_MAX:
            entries.append({**base, "status": "skip", "code": "usual_full", "reason": f"常用技能最多 {USUAL_MAX} 个，放不下了"})
        else:
            planned.append(skill_id)
            entries.append({**base, "status": "create"})
    return entries


def plan(owner_hash: str, template_id: str, bot_id=None, leave_out=None, *, create: bool = False) -> dict:
    """What applying would do, worked out against what he has now; writes nothing (``create=True``, used by ``apply`` only, makes 「助理」)."""
    template = _template(template_id)
    left = _left_out(template, leave_out)
    target = _target(owner_hash, bot_id, create=create)
    skills, resolved, all_skills = _skill_entries(owner_hash, template, left)
    skill_names = {s["key"]: s["name"] for s in template["skills"]}
    return {"template": template_id, "label": template["label"], "target": target, "resolved": resolved,
            "skill": skills, "memory": _memory_entries(owner_hash, template, left, target["layer"]),
            "brief": _brief_entries(owner_hash, template, left, target, resolved, skill_names),
            "usual": _usual_entries(template, left, target, resolved, all_skills)}


def _shown(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in ("status", "spec")}


def _by_status(worked: dict, status: str) -> list[dict]:
    return [_shown(e) for part in PART_ORDER for e in worked[part] if e["status"] == status]


def preview(owner_hash: str, template_id: str, bot_id=None, leave_out=None) -> dict:
    """What a template would write on his data, as the card and the page show it.  Read-only: not even 「助理」 is made."""
    worked = plan(owner_hash, template_id, bot_id, leave_out)
    from .kernel import wake
    mode = wake.mode()
    will_create = _by_status(worked, "create")
    for entry in will_create:
        if entry["part"] == "brief":
            brief = next(b for b in TEMPLATES[template_id]["briefs"] if b["key"] == entry["key"])
            try:
                entry["next_run_at"] = (agent_tasks.preview_task(owner_hash, brief_fields(brief)) or {}).get("next_run_at")
            except agent_tasks.TaskError:
                entry["next_run_at"] = None
    target = worked["target"]
    return {"template": template_id, "label": worked["label"],
            "target": {"bot_id": target["layer"], "bot_name": target["bot_name"], "scope": target["scope"]},
            "will_create": will_create, "reuse": _by_status(worked, "reuse"), "skip": _by_status(worked, "skip"),
            "notes": notes(mode), "duty_mode": mode}


# ---- apply -----------------------------------------------------------------------------------------------------------------------

def _bot_label(owner_hash: str, bot_id) -> tuple[str, str]:
    """(name, scope) of the bot an application went to: 「助理」 (global layer) when ``bot_id`` is None."""
    if bot_id is None:
        found = _default_bot(owner_hash)
        return (found["name"] if found else agent_bots.DEFAULT_NAME), "global"
    bot = agent_bots.get_bot(owner_hash, str(bot_id))
    return (bot["name"] if bot else "已删除的 bot"), "bot"


def _application(owner_hash: str, row) -> dict:
    name, scope = _bot_label(owner_hash, row.bot_id)
    return {"id": str(row.id), "template": row.template, "label": TEMPLATES.get(row.template, {}).get("label", row.template),
            "bot_id": str(row.bot_id) if row.bot_id else None, "bot_name": name, "scope": scope,
            "applied_at": row.applied_at.isoformat() if row.applied_at else None,
            "undone_at": row.undone_at.isoformat() if row.undone_at else None}


def _empty_created() -> dict:
    return {"profile_item_ids": [], "task_ids": [], "skill_ids": [], "usual_added": [], "labels": {}}


def _open_record(owner_hash: str, template_id: str, layer) -> uuid.UUID:
    with SessionLocal() as db:
        row = RoleTemplateApplication(owner_hash=owner_hash, template=template_id, bot_id=uuid.UUID(layer) if layer else None,
                                      applied_at=datetime.now(UTC), created=_empty_created(), skipped=[])
        db.add(row)
        db.commit()
        return row.id


def _save_record(record_id, created: dict, skipped: list[dict]) -> None:
    """The record as it stands: written after every step and once more in ``finally``, so an exception half-way still leaves what was written
    findable for ``undo``.  A record that holds nothing is removed."""
    with SessionLocal() as db:
        row = db.get(RoleTemplateApplication, record_id)
        if row is None:
            return
        if not (created["profile_item_ids"] or created["task_ids"] or created["skill_ids"] or created["usual_added"]):
            db.delete(row)
        else:
            row.created, row.skipped = copy.deepcopy(created), copy.deepcopy(skipped)
        db.commit()


def apply(owner_hash: str, template_id: str, bot_id=None, leave_out=None) -> dict:
    """Write what ``plan`` says through the services his own pages use: skills, then memory, then briefs, then usual skills.  Nothing he has is
    changed: a duplicate is reused, what does not fit is skipped with its reason.  ``application`` is None when nothing was created."""
    worked = plan(owner_hash, template_id, bot_id, leave_out, create=True)
    target = worked["target"]
    reused = _by_status(worked, "reuse")
    skipped = _by_status(worked, "skip")
    if not any(e["status"] == "create" for part in PART_ORDER for e in worked[part]):
        return {"application": None, "created": [], "reused": reused, "skipped": skipped}
    record_id = _open_record(owner_hash, template_id, target["layer"])
    created, made = _empty_created(), []
    ids = dict(worked["resolved"])               # template skill key -> id, or None once it could not be made

    def made_one(entry: dict, item_id: str, bucket: str | None) -> None:
        made.append({**_shown(entry), "id": item_id})
        if bucket:
            created[bucket].append(item_id)
            created["labels"][item_id] = entry["label"]

    def refuse(entry: dict, code: str, reason: str) -> None:
        skipped.append({**_shown(entry), "code": code, "reason": reason})

    try:
        for entry in worked["skill"]:
            if entry["status"] != "create":
                continue
            spec = entry["spec"]
            try:
                row = agent_skills.create_skill(owner_hash, {"name": spec["name"], "description": spec["description"], "body": spec["body"],
                                                             "output_template": spec["output_template"], "allowed_tools": list(spec["allowed_tools"])})
            except agent_skills.SkillError as exc:
                ids[entry["key"]] = None
                refuse(entry, str(exc), "没有创建")
                continue
            ids[entry["key"]] = row["id"]
            made_one(entry, row["id"], "skill_ids")
            _save_record(record_id, created, skipped)
        for entry in worked["memory"]:
            if entry["status"] != "create":
                continue
            try:
                result = agent_profile.add_item(owner_hash, kind=entry["kind"], text=entry["text"], quote=entry["text"], message=entry["text"],
                                                origin="manual", topic=None, bot_id=target["layer"])
            except agent_profile.ProfileError as exc:
                refuse(entry, MEMORY_FULL if "full" in str(exc) else str(exc), "没有写入")
                continue
            if result["status"] != "added":
                reused.append({**_shown(entry), "reason": REUSE_MEMORY})
                continue
            item_id = result["item"]["id"]
            made_one(entry, item_id, "profile_item_ids")
            _save_record(record_id, created, skipped)
            agent_profile.set_template(owner_hash, item_id, template_id)
        for entry in worked["brief"]:
            if entry["status"] != "create":
                continue
            brief = next(b for b in TEMPLATES[template_id]["briefs"] if b["key"] == entry["key"])
            skill_id = ids.get(entry["skill_key"]) if entry["skill_key"] else None
            if skill_id and skill_id.startswith(_NEW):
                skill_id = None
            try:
                row = agent_tasks.create_task(owner_hash, brief_fields(brief, skill_id=skill_id, bot_id=target["bot_id"]))
            except agent_tasks.TaskError as exc:
                refuse(entry, str(exc), "没有创建")
                continue
            made_one(entry, row["id"], "task_ids")
            _save_record(record_id, created, skipped)
        wanted = []
        for entry in worked["usual"]:
            if entry["status"] != "create":
                continue
            skill_id = ids.get(entry["key"]) if entry["key"] in ids else entry["skill_id"]
            if skill_id and not skill_id.startswith(_NEW):
                wanted.append((entry, skill_id))
        if wanted and target["bot_id"]:
            current = list((agent_bots.get_bot(owner_hash, target["bot_id"]) or {}).get("skills") or [])
            merged, added = list(current), []
            for entry, skill_id in wanted:
                if skill_id in merged:
                    continue
                if len(merged) >= USUAL_MAX:
                    refuse(entry, "usual_full", f"常用技能最多 {USUAL_MAX} 个，放不下了")
                    continue
                merged.append(skill_id)
                added.append((entry, skill_id))
            if added:
                try:
                    agent_bots.update_bot(owner_hash, target["bot_id"], {"skills": merged})
                except (agent_skills.SkillError, agent_bots.BotError) as exc:
                    for entry, _ in added:
                        refuse(entry, str(exc), "没有加进常用技能")
                else:
                    for entry, skill_id in added:
                        made_one(entry, skill_id, "usual_added")
    finally:
        _save_record(record_id, created, skipped)
    if not made:
        return {"application": None, "created": [], "reused": reused, "skipped": skipped}
    with SessionLocal() as db:
        application = _application(owner_hash, db.get(RoleTemplateApplication, record_id))
    return {"application": application, "created": made, "reused": reused, "skipped": skipped}


# ---- what an application holds, and taking it back -----------------------------------------------------------------------------

def _items(owner_hash: str, created: dict, bot_id) -> list[dict]:
    """Each thing an application recorded, as it is now: ``{part, id, label, there, note}``.  The label is its current text or name (he may have
    edited it) or, once it is gone, the one the record kept."""
    labels = created.get("labels") or {}
    texts = {i["id"]: i["text"] for i in agent_profile.list_items(owner_hash)}
    tasks = {t["id"]: t for t in agent_tasks.list_tasks(owner_hash)}
    skills = {s["id"]: s for s in agent_skills.list_skills(owner_hash)}
    bot = _default_bot(owner_hash) if bot_id is None else agent_bots.get_bot(owner_hash, str(bot_id))
    usual = set((bot or {}).get("skills") or [])
    own_tasks, own_skills = set(created.get("task_ids") or []), set(created.get("skill_ids") or [])
    out = []
    for item_id in created.get("profile_item_ids") or []:
        out.append({"part": "memory", "id": item_id, "label": texts.get(item_id) or labels.get(item_id, ""), "there": item_id in texts, "note": ""})
    for item_id in created.get("task_ids") or []:
        task = tasks.get(item_id)
        out.append({"part": "brief", "id": item_id, "label": task["name"] if task else labels.get(item_id, ""), "there": task is not None, "note": ""})
    for item_id in created.get("skill_ids") or []:
        skill = skills.get(item_id)
        others = sum(1 for t in tasks.values() if t.get("skill_id") == item_id and t["id"] not in own_tasks)
        out.append({"part": "skill", "id": item_id, "label": skill["name"] if skill else labels.get(item_id, ""), "there": skill is not None,
                    "note": f"还有 {others} 个别的例行任务在用它" if skill and others else ""})
    for item_id in created.get("usual_added") or []:
        if item_id in own_skills:
            continue
        skill = skills.get(item_id)
        out.append({"part": "usual", "id": item_id, "label": skill["name"] if skill else labels.get(item_id, ""), "there": item_id in usual, "note": ""})
    return out


def list_applications(owner_hash: str) -> list[dict]:
    """His applications, newest first, each with what is still there (``still_there``: memory, brief, skill, usual) and every item."""
    with SessionLocal() as db:
        rows = list(db.scalars(select(RoleTemplateApplication).where(RoleTemplateApplication.owner_hash == owner_hash)
                               .order_by(RoleTemplateApplication.applied_at.desc())))
        for row in rows:
            db.expunge(row)
    listed = []
    for row in rows:
        items = _items(owner_hash, row.created or {}, row.bot_id)
        there = {part: sum(1 for i in items if i["part"] == part and i["there"]) for part in ("memory", "brief", "skill", "usual")}
        listed.append({**_application(owner_hash, row), "still_there": there, "items": items})
    return listed


def _drop_from_usual(owner_hash: str, bot_id, ids: set[str]) -> None:
    bot = _default_bot(owner_hash) if bot_id is None else agent_bots.get_bot(owner_hash, str(bot_id))
    if not bot or not ids:
        return
    current = list(bot.get("skills") or [])
    remaining = [x for x in current if x not in ids]
    if remaining != current:
        try:
            agent_bots.update_bot(owner_hash, bot["id"], {"skills": remaining})
        except (agent_skills.SkillError, agent_bots.BotError):
            pass        # his own list holds something that no longer validates: leave it as it is rather than guess


def undo(owner_hash: str, application_id, leave_out=None) -> dict:
    """Take back what one application recorded and is still there: memory lines (edited ones too), briefs, the skills it made and the usual
    skills it added.  ``leave_out`` ids stay.  Anything already gone is listed, anything not recorded is never touched.
    Returns ``{removed, gone, kept}``."""
    try:
        key = uuid.UUID(str(application_id))
    except (TypeError, ValueError) as exc:
        raise RoleTemplateError("application_not_found") from exc
    with SessionLocal() as db:
        row = db.get(RoleTemplateApplication, key)
        if row is None or row.owner_hash != owner_hash:
            raise RoleTemplateError("application_not_found")
        if row.undone_at is not None:
            raise RoleTemplateError("already_undone")
        created, bot_id = copy.deepcopy(row.created or {}), row.bot_id
    keep = {str(x) for x in (leave_out or [])}
    recorded = {str(x) for bucket in ("profile_item_ids", "task_ids", "skill_ids", "usual_added") for x in created.get(bucket) or []}
    if keep - recorded:
        raise RoleTemplateError("unknown_leave_out")
    removed, gone, kept, todo = [], [], [], []
    for item in _items(owner_hash, created, bot_id):
        shown = {"part": item["part"], "id": item["id"], "label": item["label"]}
        if not item["there"]:
            gone.append({**shown, "reason": GONE})
        elif item["id"] in keep:
            kept.append(shown)
        else:
            todo.append(shown)
    _drop_from_usual(owner_hash, bot_id, {i["id"] for i in todo if i["part"] in ("skill", "usual")})
    deleters = {"memory": agent_profile.delete_item, "brief": agent_tasks.delete_task, "skill": agent_skills.delete_skill}
    for shown in todo:
        deleter = deleters.get(shown["part"])
        if deleter is None or deleter(owner_hash, shown["id"]):
            removed.append(shown)
        else:
            gone.append({**shown, "reason": GONE})
    with SessionLocal() as db:
        row = db.get(RoleTemplateApplication, key)
        row.undone_at = datetime.now(UTC)
        db.commit()
    return {"removed": removed, "gone": gone, "kept": kept}
