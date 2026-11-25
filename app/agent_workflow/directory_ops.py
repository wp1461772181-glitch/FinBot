"""Stage 3a, task 2: the operations that change what the owner can already change on the page (bots, ledger entries, skills,
model settings, where proactive messages go).

One place for each operation's three jobs, shared by both engines: ``describe`` checks the input with the service function the
HTTP route calls and says what will change (the card text, old → new), ``execute`` makes the change through that same service
function, ``lookup`` tells the model which ids and names exist.  Nothing here has a validation of its own: a refusal is the
service's own code with a reason in Chinese, raised before a card exists.  A card writes nothing.
"""
from __future__ import annotations

import json
import re

from .. import agent_bots as bots
from .. import agent_model_catalog as catalog
from .. import agent_model_roles as roles
from .. import agent_skills as skills
from .. import channels, portfolio
from ..database import SessionLocal

NAMES = frozenset({"create_bot", "update_bot", "delete_transaction", "manage_skill", "set_default_model", "set_model_role", "set_channel_prefs"})
# ``delete_transaction`` is pressed through the portfolio's own write tools (``portfolio.apply_tool``), like the other ledger operations.
EXECUTED = NAMES - {"delete_transaction"}
BOT_ARGS = ("title", "description", "focus_companies", "focus_theme", "tool_scope", "all_tools", "model", "use_default_model",
            "reasoning_effort", "use_default_effort", "pinned", "hidden", "skills")
CHANNEL_WORDS = {"telegram": "Telegram", "wechat": "微信"}
ROLE_WORDS = {"earnings": ("财报判断", "财报发布后写判断的模型"), "forecast": ("预测概率", "给预测方向概率的模型"),
              "judge": ("声明法官", "核对回答声明的法官模型"), "fallback": ("备用模型", "主模型出错时顶上的备用模型"), "helper": ("小助手", "替回答跑腿查资料的小助手模型")}
ROLE_DEFAULTS = {"judge": "配置里指定的法官", "fallback": "不设备用模型", "helper": "跟随当前对话模型"}


# What a card showed as the old state is frozen with it (``expect``); at the press the state is read again and a card whose old state is
# no longer true is refused and left spent.  Every operation whose card shows an old value, and ``update_routine``, is checked this way.
FRESH = (NAMES - {"create_bot"}) | {"update_routine"}
STALE = "卡片发出后这项设置变了，没有执行；请让我重新出一张卡。"
STALE_DELETE = "这笔记录或持仓在卡片发出后变了，没有删除；请让我重新出一张卡。"
_BOT_STATE = ("name", "title", "description", "focus", "tool_scope", "model", "reasoning_effort", "pinned", "hidden", "skills")
_SKILL_STATE = ("name", "description", "body", "output_template", "allowed_tools", "version", "enabled", "status")
_ROUTINE_STATE = ("name", "kind", "instruction", "schedule_kind", "schedule_time", "every_value", "every_unit", "max_runs", "enabled", "channel",
                  "skill_id", "config", "symbols", "scope")


class Refusal(Exception):
    """The input was refused before any card: ``code`` is the service's own, ``reason`` is for the owner, ``hint`` for the model."""

    def __init__(self, code: str, reason: str | None = None, hint: str | None = None):
        super().__init__(code)
        self.code = code
        self.reason = reason or f"没有通过检查（{code}）。"
        self.hint = hint or self.reason


def snapshot(owner: str, name: str, args: dict) -> dict:
    """The state a card of ``name`` shows as the old one, as plain JSON: read when the card is made and read again at the press."""
    if name == "update_bot":
        bot = bots.get_bot(owner, args["bot_id"])
        return {k: bot[k] for k in _BOT_STATE} if bot else {"gone": True}
    if name == "manage_skill":
        skill = skills.get_skill(owner, args["skill_id"])
        return {k: skill[k] for k in _SKILL_STATE} if skill else {"gone": True}
    if name == "set_default_model":
        return {"default": _entries()[1]}
    if name == "set_model_role":
        return {"role": args["role"], "model": roles.get(owner, args["role"])}
    if name == "set_channel_prefs":
        with SessionLocal() as db:
            return channels.prefs(db, owner)
    if name == "delete_transaction":
        try:
            preview = portfolio.preview_delete(owner, args["transaction_id"])
        except portfolio.PortfolioError as failure:
            return {"gone": failure.code}
        txn = preview["txn"]
        return {"entry": [txn.id, portfolio.entry_words(txn)], "funds": [preview["funds_before"], preview["funds_after"]],
                "position": [portfolio.position_words(preview["position_before"]), portfolio.position_words(preview["position_after"])]}
    if name == "update_routine":
        from .. import agent_tasks
        task = agent_tasks.get_task(owner, args["routine_id"])
        return {k: task.get(k) for k in _ROUTINE_STATE} if task else {"gone": True}
    return {}


def _plain(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def is_stale(name: str, args: dict, owner: str) -> bool:
    """True when the old state frozen with the card (``args["_expect"]``) is no longer the state now."""
    return _plain(snapshot(owner, name, args)) != _plain(args["_expect"])


def stale_refusal(name: str) -> Refusal:
    return Refusal("card_stale", STALE_DELETE if name == "delete_transaction" else STALE)


def own_card(operation: dict) -> bool:
    """Deletions are never put on a card together with other operations: the card must say exactly one thing that cannot be undone."""
    return operation.get("name") == "delete_transaction" or (operation.get("name") == "manage_skill" and operation["arguments"].get("action") == "delete")


# --- reasons (the service's code, in words) -----------------------------------------------------------------------------

BOT_REASONS = {
    "invalid_name": "名称不能为空，最多 40 字，不能有控制字符。", "invalid_title": "职位最多 60 字。",
    "invalid_description": f"说明最多 {bots.DESCRIPTION_MAX} 字。", "invalid_focus": "关注范围的格式不对。",
    "invalid_focus_symbol": "关注公司的代码不合规：大写字母开头，最长 10 位（AAPL、BRK.B）。",
    "too_many_companies": f"关注公司最多 {bots.MAX_COMPANIES} 家。", "invalid_tool_scope": "tool_scope 要是工具名的列表。",
    "unknown_tool": "tool_scope 里有不存在的工具名；基础工具自动保留，不用写。",
    "unknown_model": "模型目录里没有这个名字；用 list_models 看有哪些。", "model_key_missing": "这个模型还没有配置密钥，不能给 bot 用。",
    "invalid_reasoning_effort": "推理强度只能是 none、minimal、low、medium、high、xhigh、max 之一。",
    "default_bot_not_hidden": "默认助理不能隐藏。", "name_taken": "已经有同名的 bot。", "too_many_bots": f"bot 已经有 {bots.MAX_BOTS} 个，不能再新建。",
    "invalid_skills": "skills 要是技能 id 的列表（最多 20 个）。", "unknown_skill": "技能 id 不存在，或还不是可用状态（草稿不行）。",
    "bot_not_found": "没有这个 bot（或不是你的）；先只带 operation 调用一次 update_bot 看 bot 列表。",
    "nothing_to_change": "和现在一模一样，没有要改的。",
}
SKILL_REASONS = {
    "invalid_name": "技能名最多 40 字，不能以空白、/、@、# 开头。", "invalid_description": "用途要一行，最多 120 字。",
    "invalid_body": "步骤不能为空，最多 6000 字。", "invalid_output_template": "输出格式最多 2000 字。",
    "invalid_allowed_tools": "allowed_tools 要是 1 到 40 个工具名。", "unknown_tool": "allowed_tools 里有不存在的工具名。",
    "code_not_allowed": "技能里不能放代码块。", "name_taken": "已经有同名的技能。",
    "skill_not_found": "没有这个技能（或不是你的）；先只带 operation 调用一次 manage_skill 看技能列表。",
    "skill_is_builtin": "内置技能不能直接改或删；可以停用它，或在技能页复制成自己的再改。",
    "skill_is_draft": "这是还没保存的草稿，要先在技能页保存才能启用或停用。", "nothing_to_change": "和现在一模一样，没有要改的。",
}
MODEL_REASONS = {
    "model_not_found": "模型目录里没有这个名字；用 list_models 看有哪些。", "invalid_name": "模型名不合规；用 list_models 看有哪些。",
    "default_from_file": "默认模型由配置文件定死了，这里改不了。", "model_from_file": "这个模型来自配置文件，不能设为默认。",
    "unknown_model": "模型目录里没有这个名字；用 list_models 看有哪些。", "unknown_role": "后台角色只有 earnings、forecast、judge、fallback、helper。",
    "invalid_channels": "渠道只能是 telegram、wechat，不能重复，至少一个；mode 只能是 first 或 all。",
    "nothing_to_change": "和现在一模一样，没有要改的。",
}


def _refuse(code: str, reasons: dict, hint: str | None = None) -> Refusal:
    return Refusal(code, reasons.get(code), hint)


# --- words ----------------------------------------------------------------------------------------------------------------

def _cut(text, limit: int = 60) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _spaced(text: str) -> str:
    """A space between Chinese and Latin letters, the way the rest of the cards write them."""
    return re.sub(r"([A-Za-z])([一-鿿])", r"\1 \2", re.sub(r"([一-鿿])([A-Za-z])", r"\1 \2", text))


def _entries() -> tuple[dict, str | None]:
    listed, default = catalog.entries()
    return {item["name"]: item for item in listed}, default


def _shown(item: dict | None, name: str | None = None, *, with_model: bool = True) -> str:
    if item is None:
        return f"{name}（已不在目录里）" if name else "无"
    shown = item["display_name"] or item["name"]
    return f"{shown}（{item['model']}）" if with_model else shown


def _default_words(by_name: dict, default: str | None) -> str:
    return f"默认模型（现为 {_shown(by_name.get(default), default)}）" if default else "默认模型"


def _model_words(name: str | None) -> str:
    by_name, default = _entries()
    return _shown(by_name.get(name), name) if name else _default_words(by_name, default)


def _skill_words(owner: str, ids) -> str:
    from . import direct
    names = direct.skill_names(owner)
    return "、".join(names.get(i, "已删除的技能") for i in ids or ()) or "无"


def _yes(value) -> str:
    return "是" if value else "否"


def _tools_line(old, new, *, created: bool = False) -> str:
    selectable = [item["name"] for item in bots.selectable_tools()]
    everything = set(selectable)
    was, now = (everything if old is None else set(old)), (everything if new is None else set(new))
    order = [*selectable, *sorted((was | now) - everything)]
    added = [t for t in order if t in now - was]
    removed = [t for t in order if t in was - now]
    if created:
        return "可用工具：" + ("全部" if new is None else "、".join(new) or "只有基础工具") + "（基础工具始终保留）"
    count = lambda scope: "全部" if scope is None else f"{len(scope)} 个"          # noqa: E731
    return (f"可用工具：{count(old)} → {count(new)}；新增：{'、'.join(added) or '无'}；去掉：{'、'.join(removed) or '无'}（基础工具始终保留）")


# --- bots ------------------------------------------------------------------------------------------------------------------

def bot_fields(args: dict, current: dict | None = None) -> dict:
    """The fields ``POST``/``PATCH /bots`` take, from the operation's arguments.  A focus is one value there (companies and theme
    together), so the half the owner did not name is carried over from ``current``, names of companies included."""
    fields = {key: args[key] for key in ("name", "title", "description", "pinned", "hidden", "skills") if args.get(key) is not None}
    if args.get("focus_companies") is not None or args.get("focus_theme") is not None:
        before = (current or {}).get("focus") or {"companies": [], "theme": None}
        names = {c["symbol"]: c.get("name") for c in before.get("companies") or []}
        listed = before.get("companies") or []
        if args.get("focus_companies") is not None:
            listed = [{"symbol": s, "name": names.get(str(s).strip().upper())} for s in args["focus_companies"]]
        theme = before.get("theme") if args.get("focus_theme") is None else args["focus_theme"]
        fields["focus"] = {"companies": listed, "theme": theme}
    if args.get("all_tools"):
        fields["tool_scope"] = None
    elif args.get("tool_scope") is not None:
        fields["tool_scope"] = args["tool_scope"]
    if args.get("use_default_model"):
        fields["model"] = None
    elif args.get("model") is not None:
        fields["model"] = args["model"]
    if args.get("use_default_effort"):
        fields["reasoning_effort"] = None
    elif args.get("reasoning_effort") is not None:
        fields["reasoning_effort"] = args["reasoning_effort"]
    return fields


def _companies(bot: dict) -> str:
    return "、".join(c["symbol"] for c in (bot.get("focus") or {}).get("companies") or []) or "无"


def _bot_error(failure: bots.BotError) -> Refusal:
    return _refuse(str(failure), BOT_REASONS)


def _create_bot_card(owner: str, args: dict) -> dict:
    fields = bot_fields(args)
    try:
        bots.usable_model(fields.get("model"))
        made = bots.create_bot(owner, fields, dry_run=True)
    except bots.BotError as failure:
        raise _bot_error(failure) from None
    lines = [f"名称：{made['name']}"]
    if made["title"]:
        lines.append(f"职位：{made['title']}")
    if made["description"]:
        lines.append(f"说明：{_cut(made['description'], 80)}")
    if _companies(made) != "无":
        lines.append(f"关注公司：{_companies(made)}")
    if made["focus"].get("theme"):
        lines.append(f"关注主题：{made['focus']['theme']}")
    lines.append(_tools_line(None, made["tool_scope"], created=True))
    lines.append(f"模型：{_model_words(made['model'])}")
    if made["reasoning_effort"]:
        lines.append(f"推理强度：{made['reasoning_effort']}")
    if made["pinned"]:
        lines.append("置顶：是")
    if made["hidden"]:
        lines.append("隐藏：是")
    if made["skills"]:
        lines.append(f"常用技能：{_skill_words(owner, made['skills'])}")
    return {"title": f"新建 bot · {made['name']}", "targets": [{"kind": made["title"] or "新的 bot"}],
            "alternative": "；".join(lines) + "。新建后它有自己的对话线；之后可以让我改它的设置，删除 bot 要在页面上操作。", "fields": fields}


def _update_bot_card(owner: str, args: dict) -> dict:
    current = bots.get_bot(owner, args["bot_id"])
    if current is None:
        raise _refuse("bot_not_found", BOT_REASONS)
    fields = bot_fields(args, current)
    try:
        bots.usable_model(fields.get("model"))
        pair = bots.preview_update(owner, args["bot_id"], fields)
    except bots.BotError as failure:
        raise _bot_error(failure) from None
    if pair is None:
        raise _refuse("bot_not_found", BOT_REASONS)
    before, after = pair
    lines = []
    for label, old, new in (("名称", before["name"], after["name"]), ("职位", before["title"] or "无", after["title"] or "无"),
                            ("说明", _cut(before["description"], 40) or "无", _cut(after["description"], 80) or "无"),
                            ("关注公司", _companies(before), _companies(after)),
                            ("关注主题", before["focus"].get("theme") or "无", after["focus"].get("theme") or "无")):
        if old != new:
            lines.append(f"{label}：{old} → {new}")
    if before["tool_scope"] != after["tool_scope"]:
        lines.append(_tools_line(before["tool_scope"], after["tool_scope"]))
    if before["model"] != after["model"]:
        lines.append(f"模型：{_model_words(before['model'])} → {_model_words(after['model'])}")
    if before["reasoning_effort"] != after["reasoning_effort"]:
        lines.append(f"推理强度：{before['reasoning_effort'] or '默认'} → {after['reasoning_effort'] or '默认'}")
    for label, key in (("置顶", "pinned"), ("隐藏", "hidden")):
        if bool(before[key]) != bool(after[key]):
            lines.append(f"{label}：{_yes(before[key])} → {_yes(after[key])}")
    if list(before["skills"]) != list(after["skills"]):
        lines.append(f"常用技能：{_skill_words(owner, before['skills'])} → {_skill_words(owner, after['skills'])}")
    if not lines:
        raise _refuse("nothing_to_change", BOT_REASONS)
    return {"title": f"修改 bot · {before['name']}", "targets": [{"kind": before["title"] or before["name"]}],
            "alternative": "；".join(lines) + "。按卡片上的内容原样生效。", "fields": fields}


# --- skills ----------------------------------------------------------------------------------------------------------------

def _skill_error(failure: skills.SkillError) -> Refusal:
    return _refuse(str(failure), SKILL_REASONS)


def skill_fields(args: dict) -> dict:
    return {key: args[key] for key in ("name", "description", "body", "output_template", "allowed_tools") if args.get(key) is not None}


def _manage_skill_card(owner: str, args: dict) -> dict:
    skill = skills.get_skill(owner, args["skill_id"])
    if skill is None:
        raise _refuse("skill_not_found", SKILL_REASONS)
    action, name = args["action"], skill["name"]
    if action in {"enable", "disable"}:
        if skill["status"] != "active":
            raise _refuse("skill_is_draft", SKILL_REASONS)
        if bool(skill["enabled"]) == (action == "enable"):
            raise Refusal("nothing_to_change", f"技能「{name}」已经是{'启用' if skill['enabled'] else '停用'}状态。")
        old, new = ("已停用", "已启用") if action == "enable" else ("已启用", "已停用")
        return {"title": f"{'启用' if action == 'enable' else '停用'}技能 · {name}", "targets": [{"kind": skill["description"]}],
                "alternative": f"状态：{old} → {new}。" + ("停用后 bot 和对话里不再能选用它。" if action == "disable" else "")}
    if skill["builtin"]:
        raise _refuse("skill_is_builtin", SKILL_REASONS)
    if action == "delete":
        return {"title": f"删除技能 · {name}", "targets": [{"kind": skill["description"]}],
                "alternative": "删除后这个技能从技能库里消失，不能撤销；已经选用它的 bot 和例行任务会找不到它。"}
    try:
        pair = skills.preview_update(owner, args["skill_id"], skill_fields(args))
    except skills.SkillError as failure:
        raise _skill_error(failure) from None
    if pair is None:
        raise _refuse("skill_not_found", SKILL_REASONS)
    before, after = pair
    lines = []
    for label, key in (("名称", "name"), ("用途", "description")):
        if before[key] != after[key]:
            lines.append(f"{label}：{before[key]} → {after[key]}")
    if before["body"] != after["body"]:
        lines.append(f"步骤：{_cut(before['body'])} → {_cut(after['body'], 120)}（{len(before['body'])} 字 → {len(after['body'])} 字）")
    if (before["output_template"] or "") != (after["output_template"] or ""):
        lines.append(f"输出格式：{_cut(before['output_template']) or '无'} → {_cut(after['output_template'], 120) or '无'}")
    if list(before["allowed_tools"]) != list(after["allowed_tools"]):
        added = [t for t in after["allowed_tools"] if t not in before["allowed_tools"]]
        removed = [t for t in before["allowed_tools"] if t not in after["allowed_tools"]]
        lines.append(f"允许的工具：{len(before['allowed_tools'])} 个 → {len(after['allowed_tools'])} 个；新增：{'、'.join(added) or '无'}；去掉：{'、'.join(removed) or '无'}")
    if not lines:
        raise _refuse("nothing_to_change", SKILL_REASONS)
    lines.append(f"版本 {before['version']} → {after['version']}")
    return {"title": f"修改技能 · {name}", "targets": [{"kind": skill["description"]}], "alternative": "；".join(lines) + "。技能只会收窄可用工具，不授权写操作。"}


# --- model settings --------------------------------------------------------------------------------------------------------

def _set_default_model_card(owner: str, args: dict) -> dict:
    name = args["name"]
    try:
        catalog.check_default(name)
    except catalog.CatalogError as failure:
        raise _refuse(str(failure), MODEL_REASONS) from None
    by_name, default = _entries()
    if name == default:
        raise Refusal("nothing_to_change", f"「{_shown(by_name[name], name, with_model=False)}」已经是默认对话模型。")
    new = by_name[name]
    text = (f"默认对话模型：{_shown(by_name.get(default), default)} → {_shown(new)}。没有单独选模型的 bot 和新对话都会用它；"
            "没有单独指定模型的后台任务（财报判断、预测概率）也跟着换。已经单独选了模型的 bot 不变。")
    if not catalog._key_for(new):
        text += "注意：这个模型还没有配置密钥，换过去之后用默认模型的对话会失败。"
    return {"title": f"设置默认对话模型 · {_shown(new, with_model=False)}", "targets": [{"kind": new["model"]}], "alternative": text}


def _role_model_words(role: str, name: str | None, by_name: dict, default: str | None) -> str:
    if name:
        return _shown(by_name.get(name), name)
    if role in ROLE_DEFAULTS:
        return ROLE_DEFAULTS[role]
    return f"服务器默认模型（现为 {_shown(by_name.get(default), default, with_model=False)}）" if default else "服务器默认模型"


def _set_model_role_card(owner: str, args: dict) -> dict:
    role, name = args["role"], args.get("model")
    try:
        roles.check_role(role, name)
    except roles.RoleError as failure:
        raise _refuse(str(failure), MODEL_REASONS) from None
    current = roles.get(owner, role)
    if current == name:
        label = ROLE_WORDS[role][0]
        raise Refusal("nothing_to_change", f"{label}已经是这样设置的。")
    by_name, default = _entries()
    label, what = ROLE_WORDS[role]
    text = f"{label}用的模型：{_role_model_words(role, current, by_name, default)} → {_role_model_words(role, name, by_name, default)}。这是{what}。"
    if name and not catalog._key_for(by_name[name]):
        text += "注意：这个模型还没有配置密钥，这项后台任务换过去之后会失败。"
    return {"title": f"设置后台模型 · {label}", "targets": [{"kind": what}], "alternative": text}


# --- channels --------------------------------------------------------------------------------------------------------------

def _route_words(wanted: list[str], mode: str) -> str:
    names = [CHANNEL_WORDS[c] for c in wanted]
    if len(names) == 1:
        text = f"只发{names[0]}"
    elif mode == "all":
        text = f"同时发{'和'.join(names)}"
    else:
        text = f"先发{names[0]}，发不出去再发{'，再发'.join(names[1:])}"
    return _spaced(text)


def _set_channel_prefs_card(owner: str, args: dict) -> dict:
    wanted, mode = list(args["channels"]), args["mode"]
    try:
        channels.check_prefs(wanted, mode)
    except ValueError as failure:
        raise _refuse(str(failure), MODEL_REASONS) from None
    with SessionLocal() as db:
        old = channels.prefs(db, owner)
        usable = {c: channels.available(db, owner, c, None) for c in wanted}
    if old == {"channels": wanted, "mode": mode}:
        raise _refuse("nothing_to_change", MODEL_REASONS)
    state = [_spaced(f"{CHANNEL_WORDS[c]}现在可用" if usable[c] else f"{CHANNEL_WORDS[c]}现在没有登录或绑定，发不出去") for c in wanted]
    text = (f"之后的主动消息（盯盘提醒、例行简报、财报通知）会：{_route_words(old['channels'], old['mode'])} → {_route_words(wanted, mode)}。"
            + "；".join(state) + "。" + ("" if any(usable.values()) else "注意：选中的渠道现在都发不出去。"))
    return {"title": "设置主动消息的去向", "targets": [{"kind": _route_words(wanted, mode)}], "alternative": text}


# --- the three jobs ----------------------------------------------------------------------------------------------------------

def describe(owner: str, name: str, args: dict) -> dict:
    """``{title, targets, alternative}`` of the card, with ``fields`` for a bot (what the press writes) and ``expect`` (the old state the card
    shows), both frozen with the card.  Raises ``Refusal`` before any card; writes nothing."""
    shown = _describe(owner, name, args)
    if name in FRESH:
        shown["expect"] = snapshot(owner, name, args)
    return shown


def _describe(owner: str, name: str, args: dict) -> dict:
    if name == "create_bot":
        return _create_bot_card(owner, args)
    if name == "update_bot":
        return _update_bot_card(owner, args)
    if name == "manage_skill":
        return _manage_skill_card(owner, args)
    if name == "set_default_model":
        return _set_default_model_card(owner, args)
    if name == "set_model_role":
        return _set_model_role_card(owner, args)
    if name == "set_channel_prefs":
        return _set_channel_prefs_card(owner, args)
    if name == "delete_transaction":
        try:
            return portfolio.describe_write(owner, name, args)
        except portfolio.PortfolioError as failure:
            hint = "只带 operation 调用一次 delete_transaction，看最近的记录和它们的 id。" if failure.code == "transaction_not_found" else None
            raise Refusal(failure.code, failure.reason, hint) from None
    raise KeyError(name)


def execute(name: str, args: dict, owner: str) -> tuple[dict, str]:
    """The press: the service function the route calls.  Returns ``(data, source)``; raises ``Refusal`` (the world changed since the card)."""
    frozen = args.get("_fields")
    if name == "create_bot":
        fields = frozen if frozen is not None else bot_fields(args)
        try:
            bots.usable_model(fields.get("model"))
            made = bots.create_bot(owner, fields)
        except bots.BotError as failure:
            raise _bot_error(failure) from None
        return {"status": "created", "id": made["id"], "name": made["name"]}, "bots"
    if name == "update_bot":
        try:
            fields = frozen if frozen is not None else bot_fields(args, bots.get_bot(owner, args["bot_id"]))
            bots.usable_model(fields.get("model"))
            changed = bots.update_bot(owner, args["bot_id"], fields)
        except bots.BotError as failure:
            raise _bot_error(failure) from None
        if changed is None:
            raise _refuse("bot_not_found", BOT_REASONS)
        return {"status": "updated", "id": changed["id"], "name": changed["name"]}, "bots"
    if name == "manage_skill":
        action = args["action"]
        try:
            if action == "delete":
                done = skills.delete_skill(owner, args["skill_id"])
                result = {"status": "deleted", "id": args["skill_id"]}
            elif action == "edit":
                done = skills.update_skill(owner, args["skill_id"], skill_fields(args))
                result = {"status": "updated", "id": args["skill_id"], "name": (done or {}).get("name"), "version": (done or {}).get("version")}
            else:
                done = skills.set_enabled(owner, args["skill_id"], action == "enable")
                result = {"status": "enabled" if action == "enable" else "disabled", "id": args["skill_id"], "name": (done or {}).get("name")}
        except skills.SkillError as failure:
            raise _skill_error(failure) from None
        if not done:
            raise _refuse("skill_not_found", SKILL_REASONS)
        return result, "skill library"
    if name == "set_default_model":
        try:
            saved = catalog.set_default(args["name"])
        except catalog.CatalogError as failure:
            raise _refuse(str(failure), MODEL_REASONS) from None
        return {"status": "set", "default_model": saved["name"]}, "model catalog"
    if name == "set_model_role":
        try:
            roles.set_role(owner, args["role"], args.get("model"))
        except roles.RoleError as failure:
            raise _refuse(str(failure), MODEL_REASONS) from None
        return {"status": "set", "role": args["role"], "model": args.get("model")}, "model roles"
    if name == "set_channel_prefs":
        try:
            saved = channels.set_prefs(owner, list(args["channels"]), args["mode"])
        except ValueError as failure:
            raise _refuse(str(failure), MODEL_REASONS) from None
        return {"status": "set", **saved}, "channels"
    raise KeyError(name)


def lookup(owner: str, name: str) -> dict:
    """What an operation's lookup call adds to its argument format: the ids and names the model needs.  Never a key."""
    by_name, default = _entries()
    models = [{"name": n, "display_name": item["display_name"], "model": item["model"], "key_set": bool(catalog._key_for(item))} for n, item in by_name.items()]
    if name == "create_bot":
        return {"models": models, "default_model": default}
    if name == "update_bot":
        return {"bots": [{"id": b["id"], "name": b["name"], "title": b["title"], "model": b["model"], "tool_scope": b["tool_scope"],
                          "focus_companies": [c["symbol"] for c in (b["focus"] or {}).get("companies") or []], "pinned": b["pinned"],
                          "hidden": b["hidden"], "is_default": b["is_default"]} for b in bots.list_bots(owner)], "models": models, "default_model": default}
    if name == "delete_transaction":
        return {"transactions": portfolio.recent_transactions(owner)}
    if name == "manage_skill":
        return {"skills": [{"id": s["id"], "name": s["name"], "description": s["description"], "enabled": s["enabled"], "status": s["status"],
                            "builtin": s["builtin"]} for s in skills.list_skills(owner)]}
    if name in {"set_default_model", "set_model_role"}:
        info = {"models": models, "default_model": default}
        if name == "set_model_role":
            info["roles"] = roles.all_roles(owner)
        return info
    if name == "set_channel_prefs":
        with SessionLocal() as db:
            return {"now": channels.prefs(db, owner), "available": {c: channels.available(db, owner, c, None) for c in channels.CHANNELS}}
    return {}
