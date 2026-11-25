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
