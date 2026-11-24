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


async def settle(run, args: dict) -> dict:
    """One ``use_skill`` call: the skill's steps and output template, or ``skill_not_found``."""
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        return tools.error("invalid_arguments")
    skill = await asyncio.to_thread(agent_skills.active, getattr(run.context, "owner_hash", ""), name=name.strip())
    if skill is None:
        return tools.error("skill_not_found")
    run.audit["skill"] = {"name": skill["name"], "version": skill["version"]}
    return {"ok": True, "data": [{"status": "skill_active", "name": skill["name"], "steps": skill["body"],
                                  "output_template": skill.get("output_template")}]}
