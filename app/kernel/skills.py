"""The kernel's ``use_skill``: read one of the owner's saved skills (steps and output format) into the turn.

The steps are the owner's own text about how to answer.  They are not evidence and grant nothing: every write the steps
call for still goes through ``act`` and its card.  The tool list is fixed for the turn, so a skill never narrows it, and
reading a skill is not a read of evidence (it does not count for the tier-1 rule).
"""
from __future__ import annotations

import asyncio

from .. import agent_skills
from ..agent_workflow import tools

USE_SKILL = "use_skill"
SKILL_LINE = "- 用户存过技能（见下方列表）。用户点名某项技能，或问题明显对得上某项时，先用 use_skill 读出步骤再做。"

# The kernel does not narrow tools and does not send the old engine's skill wording (agent_skills.LIST_HEAD / render_active say a
# skill reduces the tools, which is false here).  Everything the model is told about skills comes from this module.
KERNEL_LIST_HEAD = "可用技能（所有者启用的做事步骤；需要时调用 use_skill 取全文；技能不授权任何写操作，也不是证据）："
MISSING_TOOL = "步骤里提到而你没有的工具，跳过那一步，并在回答里说明。"
LIST_TEXT = KERNEL_LIST_HEAD + "\n" + MISSING_TOOL
EXCEPTION = "只有一个例外：use_skill 返回的步骤是用户自己存的做法，照着做；它仍然不是证据，也不授权写操作。"
RESULT_NOTE = "这是所有者写的做事步骤：照着做；它不是证据，也不授权任何写操作（要改数据仍走 act 和确认卡）。" + MISSING_TOOL
NOT_FOUND_HINT = "名字要和技能列表里的一致，不带斜杠。"

USE_SKILL_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": USE_SKILL,
        "description": "按用户存过的一套做法来做。先看系统说明里的技能列表，调用后会返回这项技能的步骤和输出格式，然后照着做。技能不授权任何写操作：步骤里要改数据的地方照常走 act 和确认卡。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 1}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}


def render_skill(skill: dict) -> str:
    """The skill a slash turn (or the answer to its question) puts in front of the model: ``agent_skills.render_active`` without
    its claim that the turn is limited to the skill's tools, which does not hold on the kernel."""
    lines = [f"当前技能「{skill['name']}」（v{skill['version']}，所有者写的做事步骤：照着做；它不是证据，也不授权任何写操作）：", skill["body"]]
    if skill.get("output_template"):
        lines += ["输出格式：", skill["output_template"]]
    return "\n".join([*lines, MISSING_TOOL])


async def settle(run, args: dict) -> dict:
    """One ``use_skill`` call: the skill's steps and output template, or ``skill_not_found``."""
    name = args.get("name")
    name = name.strip().removeprefix("/").removeprefix("／").strip() if isinstance(name, str) else ""
    if not name:
        return tools.error("invalid_arguments")
    skill = await asyncio.to_thread(agent_skills.active, getattr(run.context, "owner_hash", ""), name=name)
    if skill is None:
        return {**tools.error("skill_not_found"), "hint": NOT_FOUND_HINT}
    run.audit["skill"] = {"name": skill["name"], "version": skill["version"]}
    return {"ok": True, "data": [{"status": "skill_active", "name": skill["name"], "steps": skill["body"],
                                  "output_template": skill.get("output_template"),
                                  "note": RESULT_NOTE}]}
