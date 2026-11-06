"""U9 wiring: shadow record -> public gate -> public-marks file -> chat history API, and the owner controls.

Fixture records only; no model is called.  The judge and the short review are replaced by test doubles.
"""
import asyncio
import json
import os
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent_workflow import claim_public_wire as wire
from app.agent_workflow import claim_public_gate as gate

SECRET_REASON = "REASON-SECRET-JUDGE-FREE-TEXT"
OWNER = "x" * 80


def _sentence(idx, *, text=None, subtype="number", name="", verdict="contradiction"):
    return {"idx": idx, "text": text or f"回答句子 {idx}", "status": "ok", "verdict": verdict, "subtype": subtype,
            "name_span": name, "quote": "Holder A removed 21,071,170 shares", "quote_verified": True,
            "quote_ordinal": 1, "reason": SECRET_REASON, "short_review": {"status": "ok", "passed": True}}


def _record(turn_id, sentences):
    return {"schema": "claim-shadow-v1", "turn_id": turn_id, "outcome": "judged",
            "sources": {"1": {"complete_sent": True, "truncated": False}}, "sentences": sentences}


@pytest.fixture
def shadow(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path))
    monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: cred == OWNER)
    wire._READ_CACHE.clear()
    return tmp_path


def _mark_ids(path):
    return [m["id"] for line in path.read_text(encoding="utf-8").splitlines() for m in json.loads(line)["marks"]]


def test_production_state_starts_in_auto_and_pre_review_code_is_kept():
    state = wire.production_state()
    assert state["phase"] == "auto" and state["paused"] is False and state["pre_review"] == []
    # The gate's own default is unchanged: the pre-review path still exists and is still the module default.
    assert gate.new_state()["phase"] == "pre_review"


def test_qualifying_mark_is_stored_and_state_file_is_auto(shadow):
    shown = wire.process_record(shadow, _record("turn-a", [_sentence(0), _sentence(1, verdict="supported")]))
    assert len(shown) == 1
    state = gate.load_state(shadow / wire.STATE_NAME)
    assert state["phase"] == "auto" and len(state["displayed"]) == 1
    assert stat.S_IMODE(os.stat(shadow / wire.STATE_NAME).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(shadow / wire.MARKS_NAME).st_mode) == 0o600
    assert _mark_ids(shadow / wire.MARKS_NAME) == shown


def test_nothing_is_written_when_no_sentence_qualifies(shadow):
    assert wire.process_record(shadow, _record("turn-b", [_sentence(0, verdict="supported")])) == []
    assert not (shadow / wire.MARKS_NAME).exists() and not (shadow / wire.STATE_NAME).exists()


def test_reprocessing_the_same_turn_is_idempotent(shadow):
    record = _record("turn-c", [_sentence(0)])
    first = wire.process_record(shadow, record)
    second = wire.process_record(shadow, record)
    assert first == second
    assert len((shadow / wire.MARKS_NAME).read_text(encoding="utf-8").splitlines()) == 1
    assert len(gate.load_state(shadow / wire.STATE_NAME)["displayed"]) == 1


def test_public_read_never_carries_reason_and_only_listed_fields(shadow):
    wire.process_record(shadow, _record("turn-d", [_sentence(0, subtype="subject", name="Holder A")]))
    views = wire.public_marks_for_turns(["turn-d"])["turn-d"]
    dumped = json.dumps(views, ensure_ascii=False)
    assert SECRET_REASON not in dumped and "reason" not in dumped and "name_span" not in dumped
    view = views[0]
    assert set(view) == {"id", "sentence_idx", "marker", "hit_kind", "template", "hover"}
    assert set(view["hover"]) == {"answer_sentence", "evidence"}
    assert set(view["hover"]["evidence"]) == {"ordinal", "quote", "completeness"}
    assert view["hover"]["answer_sentence"] == "回答句子 0"
    assert view["template"] == "请对照来源 [1] 中关于「Holder A」的原文"
    assert view["hit_kind"] == "subject" and view["hover"]["evidence"]["ordinal"] == 1


def test_pause_hides_reads_and_new_marks_go_to_shadow_only(shadow):
    wire.process_record(shadow, _record("turn-e", [_sentence(0)]))
    assert "turn-e" in wire.public_marks_for_turns(["turn-e"])
    wire.manual_pause(shadow, "owner check")
    assert wire.public_marks_for_turns(["turn-e"]) == {}
    assert wire.process_record(shadow, _record("turn-f", [_sentence(0)])) == []
    state = gate.load_state(shadow / wire.STATE_NAME)
    assert len(state["displayed"]) == 1  # the paused candidate was not displayed
    assert state["paused"] and state["pause_reason"].startswith("manual (owner)")


def test_resume_needs_replay_reference_and_is_kept(shadow):
    wire.process_record(shadow, _record("turn-g", [_sentence(0)]))
    wire.manual_pause(shadow, "check")
    with pytest.raises(ValueError):
        wire.manual_resume(shadow, replay_ref="", note="n")
    wire.manual_resume(shadow, replay_ref="replay-1", note="frozen set re-run")
    assert "turn-g" in wire.public_marks_for_turns(["turn-g"])
    assert gate.load_state(shadow / wire.STATE_NAME)["resumes"][0]["replay_ref"] == "replay-1"
    with pytest.raises(KeyError):  # not paused any more
        wire.manual_resume(shadow, replay_ref="replay-2", note="again")


def test_two_confirmed_mislabels_by_review_pause_display(shadow):
    wire.process_record(shadow, _record("turn-h1", [_sentence(0)]))
    wire.process_record(shadow, _record("turn-h2", [_sentence(0)]))
    ids = _mark_ids(shadow / wire.MARKS_NAME)
    assert len(ids) == 2
    assert wire.review_mark(shadow, ids[0], "confirmed_mislabel")["paused"] is False
    assert "turn-h2" in wire.public_marks_for_turns(["turn-h2"])
    status = wire.review_mark(shadow, ids[1], "confirmed_mislabel")
    assert status["paused"] is True and status["regression"] == 2
    assert wire.public_marks_for_turns(["turn-h1", "turn-h2"]) == {}


def test_owner_api_review_pause_resume_and_non_owner_refused(shadow):
    app = FastAPI()
    from app.agent_public_marks_api import router
    app.include_router(router)
    client = TestClient(app)
    wire.process_record(shadow, _record("turn-i1", [_sentence(0)]))
    wire.process_record(shadow, _record("turn-i2", [_sentence(0)]))
    ids = _mark_ids(shadow / wire.MARKS_NAME)
    headers = {"x-chat-session": OWNER}

    assert client.get("/agent-chat/public-marks/status").status_code == 403
    assert client.post("/agent-chat/public-marks/review", json={"mark_id": ids[0], "outcome": "ok"}).status_code == 403
    assert client.post("/agent-chat/public-marks/review", json={"mark_id": ids[0], "outcome": "ok"},
                       headers={"x-chat-session": "wrong"}).status_code == 403

    assert client.post("/agent-chat/public-marks/review", json={"mark_id": "abcdef", "outcome": "ok"}, headers=headers).status_code == 404
    r = client.post("/agent-chat/public-marks/review", json={"mark_id": ids[0], "outcome": "confirmed_mislabel"}, headers=headers)
    assert r.status_code == 200 and r.json()["paused"] is False
    assert client.post("/agent-chat/public-marks/review", json={"mark_id": ids[0], "outcome": "ok"}, headers=headers).status_code == 409
    r = client.post("/agent-chat/public-marks/review", json={"mark_id": ids[1], "outcome": "confirmed_mislabel"}, headers=headers)
    assert r.json()["paused"] is True and "confirmed mislabels" in r.json()["pause_reason"]

    assert client.post("/agent-chat/public-marks/resume", json={"replay_ref": "r1", "note": "n"}, headers=headers).status_code == 200
    assert client.post("/agent-chat/public-marks/resume", json={"replay_ref": "r1", "note": "n"}, headers=headers).status_code == 409
    assert client.post("/agent-chat/public-marks/pause", json={"reason": "stop"}, headers=headers).json()["paused"] is True
    assert client.get("/agent-chat/public-marks/status", headers=headers).json()["paused"] is True


def test_shadow_run_writes_record_then_marks_then_history_api_returns_them(shadow, monkeypatch):
    """End to end inside the shadow task: the judge is a fixture that returns a contradiction with a verified quote."""
    from app.agent_workflow import claim_shadow
    from app.agent_workflow.claim_judge import JudgeResult
    from app import agent_chat_stream

    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
    claim_shadow.reset_state()
    claim_shadow.set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "k"}))
    # The judge is replaced at its import site, not by the shadow test hook: the hook also switches the short review off.
    monkeypatch.setattr("app.agent_workflow.claim_judge.judge_claims", AsyncMock(return_value=JudgeResult(
        status="ok", verdict="contradiction", reason=SECRET_REASON, quote="revenue rose 8%",
        quote_verified=True, quote_ordinal=1, subtype="number")))
    monkeypatch.setattr("app.agent_workflow.claim_short_review.review_candidate", AsyncMock(return_value={"status": "ok", "passed": True}))
    turn_id = "11111111-2222-4333-8444-555555555555"
    snapshot = claim_shadow.ShadowTurn(
        turn_id=turn_id, conversation_id="c1", bot_id=None, question="Northwind 营收？",
        answer="Northwind 第三季度营收下降 8% [1]。", status="succeeded", reason="normal", route="A",
        citations=({"ordinal": 1, "quote": "revenue rose 8%", "source_type": "official_filing",
                    "saved_text": "full_document", "check_text": "revenue rose 8% in Q3"},),
        code_flags={}, answer_model="openrouter/deepseek/deepseek-v4-flash", identity_credential=OWNER)

    asyncio.run(claim_shadow._run(snapshot))

    records = [json.loads(line) for path in shadow.glob("*.jsonl") if path.name != wire.MARKS_NAME
               for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1 and records[0]["turn_id"] == turn_id and records[0]["outcome"] == "judged"
    assert gate.load_state(shadow / wire.STATE_NAME)["phase"] == "auto"
    assert len(_mark_ids(shadow / wire.MARKS_NAME)) == 1
    claim_shadow.reset_state()

    row = lambda seq, role, content: {"role": role, "content": content, "status": "complete", "turn_id": turn_id,
                                      "tool_calls": None, "tool_call_id": None, "sequence": seq}
    page = {"messages": [row(1, "user", "Northwind 营收？"), row(2, "assistant", "Northwind 第三季度营收下降 8% [1]。")],
            "has_more": False, "next_before": None, "compactions": []}

    async def fake_page(*args, **kwargs):
        return page

    monkeypatch.setattr(agent_chat_stream, "owned_message_page", fake_page)
    body = asyncio.run(agent_chat_stream.get_messages(conversation_id="c1", before=None, limit=20, x_chat_session=OWNER))
    assistant = [m for m in body["messages"] if m["role"] == "assistant"][0]
    assert len(assistant["public_marks"]) == 1
    mark = assistant["public_marks"][0]
    # The shadow's sentence unit is the text without its closing punctuation; the browser matches it inside the line.
    assert mark["hover"]["answer_sentence"] == "Northwind 第三季度营收下降 8% [1]"
    assert SECRET_REASON not in json.dumps(body, ensure_ascii=False)
    user = [m for m in body["messages"] if m["role"] == "user"][0]
    assert "public_marks" not in user

    wire.manual_pause(shadow, "check")
    body = asyncio.run(agent_chat_stream.get_messages(conversation_id="c1", before=None, limit=20, x_chat_session=OWNER))
    assert all("public_marks" not in m for m in body["messages"])


def test_missing_shadow_dir_means_no_marks(monkeypatch):
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_DIR", raising=False)
    assert wire.public_marks_for_turns(["anything"]) == {}
    assert wire.shadow_dir() is None
