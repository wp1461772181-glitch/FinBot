"""Owner-only routes for the owner's own watch rules (the web page's side of what ``act`` does with a confirmation card).

Same owner check as ``portfolio_api``.  A refused rule is a 422 with a short code and the reason in Chinese; every write refreshes the
sentinel's snapshot (inside ``app.watch_rules``)."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import watch_rules, watch_rules_view
from .agent_chat_store import owner_hash
from .agent_chat_stream import _owner_only

router = APIRouter(prefix="/agent-chat/watch-rules", tags=["watch-rules"])


class LevelBody(BaseModel):
    threshold: float
    level: Literal["remind", "urgent"]


class RuleBody(BaseModel):
    symbol: str | None = Field(default=None, max_length=12)
    metric: str | None = Field(default=None, max_length=24)
    direction: str | None = Field(default=None, max_length=8)
    levels: list[LevelBody] | None = Field(default=None, max_length=2)
    window_days: int | None = None
    repeat: str | None = Field(default=None, max_length=8)
    expires_on: str | None = Field(default=None, max_length=10)      # on a change: null or "" removes the last day
    quote: str | None = Field(default=None, max_length=400)


def _refused(exc: watch_rules.WatchRuleError) -> HTTPException:
    return HTTPException(404 if exc.code == "rule_not_found" else 422, {"error_code": exc.code, "reason": exc.reason})


def _fields(body: RuleBody) -> dict:
    return {key: value for key, value in body.model_dump(exclude={"quote"}).items() if value is not None}


@router.get("")
async def list_endpoint(x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    return {"rules": await asyncio.to_thread(watch_rules.list_rules, owner), "defaults": [r for r in await asyncio.to_thread(watch_rules_view.rows, owner) if r["kind"] == watch_rules_view.DEFAULT]}


@router.post("")
async def create_endpoint(body: RuleBody, x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    try:
        return await asyncio.to_thread(watch_rules.create, owner, _fields(body), body.quote or "")
    except watch_rules.WatchRuleError as exc:
        raise _refused(exc)


@router.patch("/{rule_id}")
async def update_endpoint(rule_id: str, body: RuleBody, x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    try:
        wipe = ("expires_on",) if "expires_on" in body.model_fields_set and not body.expires_on else ()      # explicit null or "" clears it
        return await asyncio.to_thread(lambda: watch_rules.update(owner, rule_id, _fields(body), body.quote, clear=wipe))
    except watch_rules.WatchRuleError as exc:
        raise _refused(exc)


@router.delete("/{rule_id}")
async def delete_endpoint(rule_id: str, x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    try:
        return await asyncio.to_thread(watch_rules.delete, owner, rule_id)
    except watch_rules.WatchRuleError as exc:
        raise _refused(exc)
