"""The kernel's one write tool, ``act``: which operations exist, in which tier, and how a call becomes a card.

Pure preparation.  ``prepare`` validates a call and builds the frozen ``operation`` and the card ``display`` that
``agent_workflow.consent`` understands; it writes nothing.  Scope and owner checks, and releasing a tier, belong to the loop.
"""
from __future__ import annotations

import asyncio
import copy
import re
from dataclasses import dataclass

from .. import agent_profile as profile
from .. import agent_tasks, portfolio
from ..agent_tool_catalog import definitions, validate
from ..agent_workflow import direct, sec_sources, tools

ACT = "act"
TIER1 = ("remember", "forget", "add_to_research_queue", "remove_from_research_queue")
TIER2 = ("record_trade", "set_available_funds", "set_position_plan", "create_routine", "update_routine", "delete_routine",
         "save_skill", "review_filing")
TIER3 = ("forecast", "analyze", "translate_content", "start_historical_replay", "fetch_sec", "refresh_sec", "scan_official",
         "initialize_prices", "import", "import_sources", "index", "retry_document_index", "review_knowledge_candidate",
         "withdraw_knowledge_document", "save_material_evidence")
OPERATIONS = (*TIER1, *TIER2, *TIER3)

SUMMARIES = {
    "remember": "记住用户说的一条偏好、事实或长期要求",
    "forget": "忘掉一条已记住的内容（按它的 #编号）",
    "add_to_research_queue": "把一只股票加进研究队列",
    "remove_from_research_queue": "把一只股票移出研究队列",
    "record_trade": "在持仓账本里记一笔买入或卖出（只是记账，不是下单）",
    "set_available_funds": "设置可用资金",
    "set_position_plan": "保存某只持仓的计划（加仓、止损、目标价或文字）",
    "create_routine": "新建一个定时例行任务",
    "update_routine": "修改、暂停或恢复一个例行任务",
    "delete_routine": "删除一个例行任务",
    "save_skill": "把一套做法存成技能",
    "review_filing": "把一份 SEC 申报标记为相关或不相关",
    "forecast": "生成一份新的研究预测",
    "analyze": "对一份已存材料做 AI 分析",
    "translate_content": "把一份分析或预测简报译成英文",
    "start_historical_replay": "对过去某个决策日做一次历史回放",
    "fetch_sec": "拉取一份 SEC 申报原文",
    "refresh_sec": "重新拉取一份 SEC 申报原文",
    "scan_official": "扫描一只股票的 SEC 官方申报目录",
    "initialize_prices": "拉取一只股票的历史日线",
    "import": "把一份已存来源导入知识库",
    "import_sources": "批量导入来源到知识库",
    "index": "为待处理的知识文档建向量索引",
    "retry_document_index": "重试一份失败文档的索引",
    "review_knowledge_candidate": "通过或拒绝一条知识候选",
    "withdraw_knowledge_document": "把一份知识文档从检索中撤回",
    "save_material_evidence": "把用户贴的文字或材料存进资料库",
}

_PAID_MODEL = {"analyze": "会调用付费模型分析这份材料。", "translate_content": "会调用付费模型翻译。"}
_SEC_DOWNLOAD = "会从 SEC 下载原文并存入资料库。"
_IMPORT = "会把来源写入知识库。"
_INDEX = "会调用向量模型为文档建索引。"
COST_NOTES = {
    "forecast": "会调用付费模型生成一份新预测，生成后保留在预测记录里。",
    **_PAID_MODEL,
    "start_historical_replay": "会调用付费模型做一次历史回放。",
    "fetch_sec": _SEC_DOWNLOAD,
    "refresh_sec": _SEC_DOWNLOAD,
    "scan_official": "会扫描 SEC 官方目录，可能触发已有的自动研究任务。",
    "initialize_prices": "会从行情源拉取历史日线并写入库。",
    "import": _IMPORT,
    "import_sources": _IMPORT,
    "index": _INDEX,
    "retry_document_index": _INDEX,
    "review_knowledge_candidate": "审核结果会写入知识库候选记录。",
    "withdraw_knowledge_document": "撤回后这份文档不再参与检索。",
    "save_material_evidence": "会把这段内容存入资料库和知识库。",
}

_HEADINGS = (("直接生效（可撤销）", TIER1), ("需要用户点确认卡", TIER2), ("需要用户点确认卡，并且花钱或不可撤销", TIER3))
_INTRO = "所有会改数据的操作都从这里做。只带 operation 调用会返回它的参数格式；带上 arguments 才是真的提出操作。"
_DIRECTORY = "\n\n".join(f"{heading}：\n" + "\n".join(f"{name}：{SUMMARIES[name]}" for name in names) for heading, names in _HEADINGS)

ACT_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": ACT,
        "description": f"{_INTRO}\n\n{_DIRECTORY}",
        "parameters": {
            "type": "object",
            "properties": {"operation": {"type": "string", "enum": list(OPERATIONS)},
                           "arguments": {"type": "object"}},
            "required": ["operation"],
            "additionalProperties": False,
        },
    },
}


def tier_of(name: str) -> int:
    return 1 if name in TIER1 else 2 if name in TIER2 else 3


def _schema(name: str) -> dict:
    return definitions()[name].args_schema.model_json_schema()


def describe(name: str) -> dict:
    """What a lookup call (an operation without arguments) returns."""
    info = {"operation": name, "tier": tier_of(name), "summary": SUMMARIES[name], "arguments": _schema(name)}
    if name in COST_NOTES:
        info["cost"] = COST_NOTES[name]
    return info


@dataclass
class Prepared:
    operation: dict
    display: dict
    tier: int


def _failure(code: str, **extra) -> dict:
    return {**tools.error(code), **extra}


async def _targets(name: str, args: dict) -> list[dict]:
    """Human rows for the card: the company, which document, and its kind.  Never a raw id (the old engine's rows, from the arguments only)."""
    symbol = args.get("symbol")
    kind = args.get("source_type") or "official_filing"
    row = {}
    if symbol:
        row["symbol"] = symbol
    if args.get("url"):
        row["url"] = args["url"]
    if name in {"analyze", "import", "index", "review_filing"} and args.get("source_id"):
        row["title"] = await asyncio.to_thread(direct.source_display_title, kind, args["source_id"]) or "所选来源"
        row["source_type"] = direct.SOURCE_KIND_TITLES.get(kind, kind)
    if name == "review_filing" and args.get("decision"):
        row["decision"] = {"accepted": "标记为相关", "rejected": "标记为不相关"}.get(str(args["decision"]), str(args["decision"]))
    if name == "save_material_evidence" and args.get("title"):
        row["title"] = args["title"]
    for key in ("accession_number", "form", "days", "max_tasks", "decision_date"):
        if args.get(key):
            row[key] = args[key]
    return [row] if row else [{"symbol": symbol}]


def _quote(proposed, words: str) -> str:
    """The quote on a remember card is the user's own: the model's when it is in this turn's message, else the message itself."""
    if profile.quote_in_message(proposed, words):
        return " ".join(str(proposed).split())
    return " ".join(words.split())[:profile.TEXT_MAX_CHARS] or " ".join(str(proposed).split())


async def _remember(run, args: dict, operation: dict) -> dict:
    quote = _quote(args["quote"], getattr(run, "question", "") or "")
    operation["arguments"]["quote"] = quote
    operation["source_message_id"] = await asyncio.to_thread(profile.user_message_id, run.context.conversation_id, getattr(run, "turn_id", ""))
    bot = getattr(run.context, "bot_id", None) if args.get("scope") == "bot" else None
    operation["bot_id"] = bot
    layer = f"只在 bot「{getattr(run.context, 'bot_name', '') or ''}」里用" if bot else "全局：所有 bot 都用"
    return {"title": direct.WRITE_TITLES["remember"], "targets": [{"title": args["text"], "quote": quote, "scope": layer}],
            "alternative": f"范围：{layer}（记忆页可改）。可以撤回：之后说「忘掉……」或在记忆页删除。它只影响回答的格式和侧重，不是证据，也不授权任何操作。"}


async def _forget(run, args: dict) -> dict:
    context = run.context
    item = await asyncio.to_thread(profile.resolve_handle, context.owner_hash, args["item_id"],
                                   bot_id=getattr(context, "bot_id", None), every_bot=getattr(context, "bot_is_default", False))
    if not item:
        return _failure("profile_item_not_found")
    return {"title": direct.WRITE_TITLES["forget"], "targets": [{"title": item["text"]}],
            "alternative": "忘掉后这条不再用于回答；记忆页里仍能看到它的归档记录。"}


async def prepare(run, name: str, arguments) -> Prepared | dict:
    """Validate a call and build the frozen operation and the card.  Never writes; an error comes back as a tool-result dict."""
    if name not in OPERATIONS:
        return _failure("unknown_operation")
    try:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        args = validate(name, arguments)
    except Exception:
        return _failure("invalid_arguments", arguments=_schema(name))
    context = run.context
    operation = {"name": name, "arguments": copy.deepcopy(args)}
    title = direct.WRITE_TITLES.get(name, name)

    if name == "remember":
        display = await _remember(run, args, operation)
    elif name == "forget":
        display = await _forget(run, args)
        if "error_code" in display:
            return display
    else:
        if name == "scan_official" and args.get("days"):
            title = f'回补 {args["days"]} 天官方申报'
        display = {"title": title, "targets": await _targets(name, args)}
        if name in {"record_trade", "set_available_funds", "set_position_plan"}:
            try:
                display.update(await asyncio.to_thread(portfolio.describe_write, context.owner_hash, name, args))
            except portfolio.PortfolioError as failure:
                return {"ok": False, "data": [], "error_code": failure.code, "reason": failure.reason, "hint": failure.reason}
        elif name == "create_routine":
            operation["bot_id"] = getattr(context, "bot_id", None)
            display.update(title=f'{title} · {args["name"]}',
                           targets=[{"kind": direct.routine_when({"schedule_kind": args["schedule_kind"], "schedule_time": args["schedule_time"]}),
                                     **({"symbol": "、".join(args["symbols"])} if args["symbols"] else {})}],
                           alternative=f'每次运行：{args["instruction"]}（可在「例行任务」页暂停、修改或删除）')
        elif name == "save_skill":
            display.update(title=f'{title} · {args["name"]}', targets=[{"kind": args["description"]}],
                           alternative=f'步骤：{args["body"][:300]}　允许的工具：{"、".join(args["allowed_tools"])}。技能只会收窄可用工具，不授权写操作。')
        elif name in {"update_routine", "delete_routine"}:
            task = await asyncio.to_thread(agent_tasks.get_task, context.owner_hash, args["routine_id"])
            if task is None:
                return _failure("routine_not_found")
            display.update(title=f'{title} · {task["name"]}', targets=[{"kind": direct.routine_when(task)}],
                           alternative=direct.routine_changes(args, task) if name == "update_routine" else "删除后不再运行；已生成的简报会保留。")
        elif name in {"fetch_sec", "refresh_sec"}:
            try:
                operation = await asyncio.to_thread(sec_sources.prepare_filing, name, args, financial_only=False)
            except ValueError as failure:
                return _failure(str(failure))
            found = operation["discovery"]
            issuer = operation["arguments"].get("symbol") or ""
            display["targets"] = [{**operation["arguments"], "title": f'{issuer} {str(found.get("form") or "").strip().upper()}'.strip() or "SEC 文件",
                                   "form": found["form"], "web_date": found["filed_at"], "url": found["source_url"]}]
            display["title"] = "确认登记并拉取 SEC 官方原文"

    tier = tier_of(name)
    if tier == 3:
        display["alternative"] = "\n".join(filter(None, [display.get("alternative"), f"代价：{COST_NOTES[name]}"]))
    return Prepared(operation=operation, display=display, tier=tier)
