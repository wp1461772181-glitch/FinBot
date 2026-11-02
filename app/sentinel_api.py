"""Internal endpoints for the sentinel: loopback peer plus X-Sentinel-Token (env SENTINEL_TOKEN)."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select

router = APIRouter(prefix="/agent-chat/internal/sentinel", tags=["sentinel-internal"])
logger = logging.getLogger(__name__)


class SentinelEvent(BaseModel):
    type: Literal["earnings_detected", "alert_posted"]
    payload: dict[str, Any] = {}


def require_sentinel(request: Request) -> None:
    expected = os.environ.get("SENTINEL_TOKEN", "")
    supplied = request.headers.get("X-Sentinel-Token", "")
    peer = request.client.host if request.client else ""
    try:
        loopback = ipaddress.ip_address(peer.split("%", 1)[0]).is_loopback
    except ValueError:
        loopback = False
    # A tunnel (Tailscale Funnel) reaches us from loopback too; its forwarding headers give it away.
    proxied = any(n.lower() in {"forwarded", "x-real-ip"} or n.lower().startswith("x-forwarded-") for n in request.headers)
    if not loopback or proxied:
        raise HTTPException(403, "localhost_only")
    if not expected or not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(403, "invalid_sentinel_token")


def _count_pending() -> int:
    from .database import SessionLocal
    from .forecast_v2_models import ForecastJobV2

    now = datetime.now(UTC)
    claimable = or_(
        and_(ForecastJobV2.status == "queued",
             or_(ForecastJobV2.next_attempt_at.is_(None), ForecastJobV2.next_attempt_at <= now)),
        and_(ForecastJobV2.status == "running", ForecastJobV2.lease_expires_at <= now),
    )
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(ForecastJobV2).where(claimable)) or 0)


@router.post("/events")
async def post_event(body: SentinelEvent, request: Request):
    require_sentinel(request)
    # Skeleton: accepted and logged; consumers (inbox, push) hook in with the signal tasks.
    logger.info("sentinel event %s: %s", body.type, body.payload)
    return {"accepted": True, "type": body.type}


@router.get("/pending-forecast-jobs")
async def pending_forecast_jobs(request: Request):
    """Jobs a worker could claim now (the same predicate as claim_next_job)."""
    require_sentinel(request)
    return {"pending": await asyncio.to_thread(_count_pending)}
