"""Owner-only portfolio API (personal finance assistant, Task 6).

Same owner check as ``agent_bots_api``: ``_owner_only`` answers 403 ``owner_only`` to anyone but the site owner.
A refused entry is a 422 with a short code and the reason in Chinese; nothing it carried is echoed back.
Every write ends with ``write_sentinel_snapshot`` so the sentinel's copy of positions and plans follows."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import portfolio
from .agent_chat_store import owner_hash
from .agent_chat_stream import _owner_only

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent-chat/portfolio", tags=["portfolio"])

Number = str | int | float


class TransactionBody(BaseModel):
    kind: Literal["opening", "buy", "sell", "dividend", "split", "deposit", "withdraw", "cash_adjust"]
    symbol: str | None = Field(default=None, max_length=12)
    quantity: Number | None = None
    price: Number | None = None
    fee: Number | None = None
    amount: Number | None = None
    ratio: Number | None = None
    occurred_on: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=portfolio.MAX_NOTE)


class PlanBody(BaseModel):
    plan_text: str | None = Field(default=None, max_length=portfolio.MAX_PLAN_TEXT)
    add_price: Number | None = None
    stop_price: Number | None = None
    target_price: Number | None = None


class CashBody(BaseModel):
    available_funds: Number


def _refused(exc: portfolio.PortfolioError) -> HTTPException:
    return HTTPException(422, {"error_code": exc.code, "reason": exc.reason})


def _snapshot(owner: str) -> None:
    """The write is done; a failing snapshot must not turn it into an error."""
    from .sentinel_bridge import write_sentinel_snapshot
    try:
        write_sentinel_snapshot(owner)
    except Exception:
        logger.warning("sentinel snapshot after a portfolio write failed", exc_info=True)


@router.get("")
async def portfolio_summary_endpoint(x_chat_session: str | None = Header(default=None)):
    credential = _owner_only(x_chat_session)
    return await asyncio.to_thread(portfolio.build_summary, owner_hash(credential))


@router.post("/transactions")
async def add_transaction_endpoint(body: TransactionBody, x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    try:
        result = await asyncio.to_thread(portfolio.record_transaction, owner, body.model_dump())
    except portfolio.PortfolioError as exc:
        raise _refused(exc)
    await asyncio.to_thread(_snapshot, owner)
    return result


@router.delete("/transactions/{transaction_id}")
async def delete_transaction_endpoint(transaction_id: str, x_chat_session: str | None = Header(default=None)):
    owner = owner_hash(_owner_only(x_chat_session))
    try:
        result = await asyncio.to_thread(portfolio.delete_transaction, owner, transaction_id)
    except portfolio.PortfolioError as exc:
        if exc.code == "transaction_not_found":
            raise HTTPException(404, {"error_code": exc.code, "reason": exc.reason})
        raise _refused(exc)
    await asyncio.to_thread(_snapshot, owner)
    return result


@router.put("/plans/{symbol}")
async def put_plan_endpoint(symbol: str, body: PlanBody, x_chat_session: str | None = Header(default=None)):
    """Replaces the plan: a field left out or null is cleared."""
    owner = owner_hash(_owner_only(x_chat_session))
    fields = {key: getattr(body, key) for key in ("plan_text", "add_price", "stop_price", "target_price")}
    try:
        result = await asyncio.to_thread(portfolio.set_plan, owner, symbol, fields)
    except portfolio.PortfolioError as exc:
        raise _refused(exc)
    await asyncio.to_thread(_snapshot, owner)
    return result


@router.put("/cash")
async def put_cash_endpoint(body: CashBody, x_chat_session: str | None = Header(default=None)):
    """Hand-set available funds: a ``cash_adjust`` for the difference is written."""
    owner = owner_hash(_owner_only(x_chat_session))
    try:
        result = await asyncio.to_thread(portfolio.set_available_funds, owner, body.available_funds)
    except portfolio.PortfolioError as exc:
        raise _refused(exc)
    await asyncio.to_thread(_snapshot, owner)
    return result
