"""Owner-only routes for what it keeps to look at again (``app.follow_ups``): the open ones, and cancelling one from the memory page."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header, HTTPException

from . import follow_ups
from .agent_chat_store import owner_hash
from .agent_chat_stream import _owner_only

router = APIRouter(prefix="/agent-chat", tags=["follow-ups"])


@router.get("/follow-ups")
async def list_endpoint(x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    return {"items": await asyncio.to_thread(follow_ups.open_items, owner), "max_open": follow_ups.MAX_OPEN}


@router.delete("/follow-ups/{follow_up_id}")
async def cancel_endpoint(follow_up_id: int, x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    row = await asyncio.to_thread(follow_ups.cancel, owner, follow_up_id)
    if row is None:
        raise HTTPException(404, "follow_up_not_found")
    return row
