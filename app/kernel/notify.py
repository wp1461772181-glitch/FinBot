"""The kernel's ``notify_telegram``, offered in a scheduled run only (``context.unattended``).

A routine's instruction may say when something is worth telling the owner now (「有新的就用 notify_telegram 发给我」); the old turn had
this tool and the kernel takes it over unchanged: the server picks the recipient (the owner's own channels), writes the bot's name in
front, keeps to the bot's daily count, and refuses a figure that does not carry one of this turn's evidence numbers
(``agent_telegram.notify``).  An owner who is talking to the bot is told in the answer itself, so a live turn is not offered it.
"""
from __future__ import annotations

import asyncio
import copy

from ..agent_tool_catalog import definitions, validate
from ..agent_workflow import tools

NOTIFY = "notify_telegram"


def schema() -> dict:
    """The catalogue's own definition of the tool (its description and arguments are the old turn's)."""
    policy = definitions()[NOTIFY]
    return {"type": "function", "function": {"name": policy.name, "description": policy.description,
                                             "parameters": policy.args_schema.model_json_schema()}}


async def settle(run, args: dict) -> dict:
    """Queue the message.  ``run.citations`` are this turn's numbered evidence: nothing else can be cited."""
    from .. import agent_telegram as telegram
    context = run.context
    try:
        checked = validate(NOTIFY, args)
    except Exception:
        return tools.error("invalid_arguments")
    try:
        data = await asyncio.to_thread(telegram.notify, context.owner_hash, getattr(context, "bot_id", None), checked.get("text") or "",
                                       checked.get("evidence_ids") or [], copy.deepcopy(run.citations))
    except telegram.NotifyError as refused:
        run.audit["telegram"] = "refused:" + str(refused)
        return tools.error(str(refused))
    run.audit["telegram"] = "queued"
    run.audit["telegram_sent"] = run.audit.get("telegram_sent", 0) + 1
    return {"ok": True, "data": [data]}
