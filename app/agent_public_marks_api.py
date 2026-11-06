"""Owner-only controls for the public contradiction marks (U9): review a displayed mark, pause and resume display.

Minimal by design: no page, no listing of marks.  Every route checks the same owner credential as the shadow judge
(app.agent_chat_identity.owner_credential_matches), read at call time.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.agent_workflow import claim_public_wire as wire

router = APIRouter(prefix="/agent-chat/public-marks", tags=["agent-chat-public-marks"])
NO_STORE = {"Cache-Control": "no-store"}


class ReviewBody(BaseModel):
    mark_id: str = Field(min_length=1, max_length=64, pattern=r"^[0-9a-f]+$")
    outcome: Literal["ok", "confirmed_mislabel"]


class PauseBody(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class ResumeBody(BaseModel):
    replay_ref: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=400)


def _owner_or_403(credential: str | None) -> None:
    from app.agent_chat_identity import owner_credential_matches
    if not owner_credential_matches(credential):
        raise HTTPException(403, "owner_required", headers=NO_STORE)


def _dir_or_503():
    path = wire.shadow_dir()
    if path is None:
        raise HTTPException(503, "public_marks_unconfigured", headers=NO_STORE)
    return path


@router.get("/status")
async def status(x_chat_session: str | None = Header(default=None)):
    _owner_or_403(x_chat_session)
    path = _dir_or_503()
    return JSONResponse(await asyncio.to_thread(wire.status, path), headers=NO_STORE)


@router.post("/review")
async def review(body: ReviewBody, x_chat_session: str | None = Header(default=None)):
    """Record a person's review of a displayed mark.  'confirmed_mislabel' feeds the stop-loss count."""
    _owner_or_403(x_chat_session)
    path = _dir_or_503()
    try:
        view = await asyncio.to_thread(wire.review_mark, path, body.mark_id, body.outcome)
    except KeyError:
        raise HTTPException(404, "mark_not_displayed", headers=NO_STORE)
    except ValueError:
        raise HTTPException(409, "already_reviewed", headers=NO_STORE)
    return JSONResponse(view, headers=NO_STORE)


@router.post("/pause")
async def pause(body: PauseBody, x_chat_session: str | None = Header(default=None)):
    _owner_or_403(x_chat_session)
    path = _dir_or_503()
    return JSONResponse(await asyncio.to_thread(wire.manual_pause, path, body.reason), headers=NO_STORE)


@router.post("/resume")
async def resume(body: ResumeBody, x_chat_session: str | None = Header(default=None)):
    """Resume display.  Needs a replay reference and a note (the gate's rule); history is kept."""
    _owner_or_403(x_chat_session)
    path = _dir_or_503()
    try:
        view = await asyncio.to_thread(wire.manual_resume, path, replay_ref=body.replay_ref, note=body.note)
    except KeyError:
        raise HTTPException(409, "not_paused", headers=NO_STORE)
    except ValueError:
        raise HTTPException(422, "resume_needs_replay_ref_and_note", headers=NO_STORE)
    return JSONResponse(view, headers=NO_STORE)
