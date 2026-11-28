"""Owner-only route for 「手上的事」 on the web (design 4.8 / section 11): the same list the kernel's ``list_work`` reads.

Same owner check as the watch-rules routes.  Read only: stopping a running turn stays where it is (the chat's own stop)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header

from . import work
from .agent_chat_store import owner_hash
from .agent_chat_stream import _owner_only

router = APIRouter(prefix="/agent-chat", tags=["work"])


@router.get("/work")
async def list_endpoint(x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    return {"items": await asyncio.to_thread(work.list_for, owner)}
