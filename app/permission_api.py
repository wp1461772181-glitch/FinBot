"""Owner-only route for the permission mode (``app.permission_mode``): read it, change it.  The assistant cannot change it (its route is
exempt in the operation registry): how much it may do unasked is his decision."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel

from . import permission_mode
from .agent_chat_store import owner_hash
from .agent_chat_stream import _owner_only

router = APIRouter(prefix="/agent-chat", tags=["permission"])


class ModeBody(BaseModel):
    mode: Literal["ask", "default", "full"]


@router.get("/permission-mode")
async def read_endpoint(x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    return permission_mode.view(await asyncio.to_thread(permission_mode.get, owner))


@router.put("/permission-mode")
async def write_endpoint(body: ModeBody, x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    return await asyncio.to_thread(permission_mode.set_mode, owner, body.mode)
