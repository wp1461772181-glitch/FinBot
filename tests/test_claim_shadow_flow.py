"""Integration and flow tests for claim_shadow.py and graph.py (§1, §3.4, §6.3)."""
import asyncio
import contextvars
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_workflow.claim_judge import JudgeResult, JudgeSource
from app.agent_workflow.claim_shadow import (
    DEFAULT_DAILY_CALLS,
    DEFAULT_TARGET_TURNS,
    MAX_PENDING_TURNS,
    ShadowTurn,
    _TASKS,
    enabled,
    maybe_schedule,
    reset_state,
    set_test_judge_fn,
    set_test_resolve_fn,
)
from app.agent_workflow.graph import _direct_agent_turn


@pytest.fixture(autouse=True)
def clean_shadow_state():
    reset_state()
    yield
    reset_state()


def test_switch_disabled_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW", raising=False)
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_DIR", raising=False)
    assert not enabled()

    # Relative dir also disables
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", "relative/path")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
    assert not enabled()


def test_switch_enabled_when_valid(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
    assert enabled()

    # STOP file immediately disables
    (tmp_path / "STOP").write_text("STOP", encoding="utf-8")
    assert not enabled()


def test_zero_impact_on_answer_when_switch_off(monkeypatch, tmp_path: Path):
    """When switch is off: claim_shadow_extract not imported, mock judge not called, no files."""
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW", raising=False)
    sys.modules.pop("app.agent_workflow.claim_shadow_extract", None)

    called = False

    async def fake_judge(*args, **kwargs):
        nonlocal called
        called = True
        return JudgeResult(status="ok", verdict="supported")

    set_test_judge_fn(fake_judge)

    turn_result = {
        "answer": "Northwind 第三季度营收增长 8% [1]。",
        "citations": [{"ordinal": 1, "quote": "revenue rose 8%", "source_type": "official_filing", "check_text": "full doc"}],
        "status": "succeeded",
        "reason": None,
        "route": "A",
        "audit": {"polarity_conflict": []},
    }
    context = MagicMock(unattended=False, provider="openrouter", model="deepseek/deepseek-v4-flash")
    state = {"question": "Q?", "messages": []}

    maybe_schedule(turn_result, context, state)

    assert not called
    assert "app.agent_workflow.claim_shadow_extract" not in sys.modules
    assert len(list(tmp_path.glob("*.jsonl"))) == 0


def test_direct_agent_turn_identical_output_and_check_text_stripped(monkeypatch, tmp_path: Path):
    """Answer, citations, status, unverified_lines, audit completely identical;

    stored citations lose check_text while shadow snapshot retains it.
    """
    async def _run():
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")

        # Mock owner check
        monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: True)

        set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "fake-key"}))
        set_test_judge_fn(AsyncMock(return_value=JudgeResult(status="ok", verdict="supported", quote="revenue rose 8%", quote_verified=True, quote_ordinal=1)))

        raw_citations = [{
            "ordinal": 1,
            "quote": "revenue rose 8%",
            "source_type": "official_filing",
            "saved_text": "full_document",
            "check_text": "very long checking text that will be stripped by persistable_citation",
        }]

        direct_result = {
            "answer": "Northwind 第三季度营收增长 8% [1]。",
            "citations": [dict(raw_citations[0])],
            "result_sets": [],
            "status": "succeeded",
            "reason": "normal",
            "route": "A",
            "unverified_lines": [],
            "audit": {"some_audit_key": 123},
        }

        runtime = MagicMock()
        runtime.context = MagicMock(unattended=False, provider="openrouter", model="deepseek/deepseek-v4-flash", identity_credential="owner-cred")
        state = {"question": "Northwind 营收情况？", "messages": []}

        with patch("app.agent_workflow.direct.run_direct_turn", AsyncMock(return_value=dict(direct_result))):
            with patch("app.agent_workflow.graph.get_stream_writer") as mock_writer:
                mock_write = MagicMock()
                mock_writer.return_value = mock_write

                res = await _direct_agent_turn(state, runtime)

                # Wait for background task
                if _TASKS:
                    await asyncio.gather(*list(_TASKS))

                # The returned result citations MUST NOT have check_text
                assert "check_text" not in res["citations"][0]
                assert res["citations"][0]["evidence_incomplete"] is True
                assert res["answer"] == direct_result["answer"]
                assert res["audit"] == direct_result["audit"]
                assert "shadow" not in res["audit"]  # No new keys in audit

                # But the file on disk MUST have the full text sent to judge
                files = list(tmp_path.glob("*.jsonl"))
                assert len(files) == 1
                record = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
                assert record["outcome"] == "judged"
                assert record["counted"] is True
                assert "very long checking text" in record["sources"]["1"]["text_sent"]

    asyncio.run(_run())


def test_judge_hanging_does_not_block_direct_turn(monkeypatch, tmp_path: Path):
    """When judge hangs/sleeps, _direct_agent_turn completes immediately and emits delta/done."""
    async def _run():
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
        monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: True)

        set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "fake-key"}))

        # Hanging judge
        async def hanging_judge(*args, **kwargs):
            await asyncio.sleep(100.0)
            return JudgeResult(status="ok")

        set_test_judge_fn(hanging_judge)

        direct_result = {
            "answer": "Northwind 第三季度营收增长 8% [1]。",
            "citations": [{"ordinal": 1, "quote": "rose 8%", "source_type": "official_filing"}],
            "result_sets": [],
            "status": "succeeded",
        }
        runtime = MagicMock()
        runtime.context = MagicMock(unattended=False)
        state = {"question": "Q?"}

        with patch("app.agent_workflow.direct.run_direct_turn", AsyncMock(return_value=dict(direct_result))):
            with patch("app.agent_workflow.graph.get_stream_writer") as mock_writer:
                emitted = []
                mock_writer.return_value = lambda ev: emitted.append(ev.get("event"))

                # Must return promptly
                await asyncio.wait_for(_direct_agent_turn(state, runtime), timeout=2.0)
                assert "delta" in emitted
                assert "done" in emitted

    asyncio.run(_run())


def test_maybe_schedule_exception_does_not_crash_direct_turn(monkeypatch):
    """If maybe_schedule raises internally, _direct_agent_turn completes normally."""
    async def _run():
        runtime = MagicMock()
        state = {"question": "Q?"}
        direct_result = {"answer": "answer", "citations": [], "status": "succeeded"}

        with patch("app.agent_workflow.claim_shadow.maybe_schedule", side_effect=RuntimeError("internal boom")):
            with patch("app.agent_workflow.direct.run_direct_turn", AsyncMock(return_value=direct_result)):
                with patch("app.agent_workflow.graph.get_stream_writer"):
                    res = await _direct_agent_turn(state, runtime)
                    assert res["answer"] == "answer"

    asyncio.run(_run())


def test_task_runs_in_empty_contextvars_and_is_cleaned_up(monkeypatch, tmp_path: Path):
    """Background task runs in empty contextvars Context; _DECISION_SESSION is None."""
    async def _run():
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
        monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: True)

        session_var = contextvars.ContextVar("decision_session", default=None)
        session_var.set("parent_session_value")

        task_observed_session = "not_set"

        async def fake_judge(*args, **kwargs):
            nonlocal task_observed_session
            task_observed_session = session_var.get()
            return JudgeResult(status="ok", verdict="supported")

        set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "fake"}))
        set_test_judge_fn(fake_judge)

        turn_result = {
            "answer": "Northwind 第三季度营收增长 8% [1]。",
            "citations": [{"ordinal": 1, "quote": "rose 8%", "source_type": "official_filing"}],
            "status": "succeeded",
        }
        context = MagicMock(unattended=False)
        state = {"question": "Q?"}

        maybe_schedule(turn_result, context, state)

        # In _TASKS initially
        assert len(_TASKS) == 1
        task = list(_TASKS)[0]

        await task
        # Removed from _TASKS upon completion
        assert len(_TASKS) == 0
        # Empty contextvars: parent session var was NOT inherited
        assert task_observed_session is None

    asyncio.run(_run())


def test_over_pending_turns_dropped_silently(monkeypatch, tmp_path: Path):
    """When pending tasks >= MAX_PENDING_TURNS (8), new turns are dropped silently."""
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")

    turn_result = {
        "answer": "营收增长 8% [1]。",
        "citations": [{"ordinal": 1, "quote": "8%", "source_type": "official_filing"}],
        "status": "succeeded",
    }
    context = MagicMock(unattended=False)
    state = {"question": "Q?"}

    # Fill up _TASKS with dummy tasks
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for _ in range(MAX_PENDING_TURNS):
        t = loop.create_task(asyncio.sleep(10))
        _TASKS.add(t)

    maybe_schedule(turn_result, context, state)
    assert len(_TASKS) == MAX_PENDING_TURNS  # Not added

    for t in list(_TASKS):
        t.cancel()
    loop.close()


def test_visitor_and_filter_conditions(monkeypatch, tmp_path: Path):
    """unattended, pending_request, failed, no citations, no [n] do not schedule. Visitor not judged."""
    async def _run():
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")

        # 1. Unattended
        maybe_schedule({"answer": "x[1]", "citations": [{"ordinal": 1}], "status": "succeeded"}, MagicMock(unattended=True), {})
        assert len(_TASKS) == 0

        # 2. Pending request
        maybe_schedule({"answer": "x[1]", "citations": [{"ordinal": 1}], "status": "succeeded", "pending_request": {"id": 1}}, MagicMock(unattended=False), {})
        assert len(_TASKS) == 0

        # 3. Failed status
        maybe_schedule({"answer": "x[1]", "citations": [{"ordinal": 1}], "status": "failed"}, MagicMock(unattended=False), {})
        assert len(_TASKS) == 0

        # 4. No citations
        maybe_schedule({"answer": "x[1]", "citations": [], "status": "succeeded"}, MagicMock(unattended=False), {})
        assert len(_TASKS) == 0

        # 5. No [n] marker
        maybe_schedule({"answer": "no citation here", "citations": [{"ordinal": 1}], "status": "succeeded"}, MagicMock(unattended=False), {})
        assert len(_TASKS) == 0

        # 6. Visitor (owner check fails)
        monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: False)
        set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "fake"}))
        set_test_judge_fn(AsyncMock(return_value=JudgeResult(status="ok")))

        maybe_schedule({"answer": "x[1]", "citations": [{"ordinal": 1, "quote": "x", "source_type": "official_filing"}], "status": "succeeded"}, MagicMock(unattended=False, identity_credential="guest"), {})
        if _TASKS:
            await asyncio.gather(*list(_TASKS))

        # Visitor leaves NO records on disk
        assert len(list(tmp_path.glob("*.jsonl"))) == 0

    asyncio.run(_run())


def test_counted_five_conditions_and_target_reached(monkeypatch, tmp_path: Path):
    """Verify all 5 counted conditions; all failed not counted; duplicate answer_sha256 not counted;

    target_reached written only once.
    """
    async def _run():
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_TARGET_TURNS", "2")
        monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: True)

        set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "fake"}))

        # Turn 1: All judge calls fail -> counted MUST be False
        set_test_judge_fn(AsyncMock(return_value=JudgeResult(status="timeout", error_code="timeout")))
        maybe_schedule({"turn_id": "t1", "answer": "公司第一季度营收实现稳步增长 [1]。", "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}], "status": "succeeded"}, MagicMock(unattended=False), {})
        await asyncio.gather(*list(_TASKS))

        # Turn 2: Judge call succeeds -> counted True (turn 1 of 2)
        set_test_judge_fn(AsyncMock(return_value=JudgeResult(status="ok", verdict="supported")))
        maybe_schedule({"turn_id": "t2", "answer": "公司第二季度营收实现稳步增长 [1]。", "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}], "status": "succeeded"}, MagicMock(unattended=False), {})
        await asyncio.gather(*list(_TASKS))

        # Turn 3: Duplicate answer_sha256 of Turn 2 -> counted MUST be False
        maybe_schedule({"turn_id": "t3", "answer": "公司第二季度营收实现稳步增长 [1]。", "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}], "status": "succeeded"}, MagicMock(unattended=False), {})
        await asyncio.gather(*list(_TASKS))

        # Turn 4: Fresh answer -> counted True (turn 2 of 2, hits TARGET)
        maybe_schedule({"turn_id": "t4", "answer": "公司第四季度营收实现稳步增长 [1]。", "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}], "status": "succeeded"}, MagicMock(unattended=False), {})
        await asyncio.gather(*list(_TASKS))

        # Turn 5: Already reached TARGET -> writes target_reached outcome once, does not call model
        judge_called = False

        async def check_called(*args, **kwargs):
            nonlocal judge_called
            judge_called = True
            return JudgeResult(status="ok")

        set_test_judge_fn(check_called)
        maybe_schedule({"turn_id": "t5", "answer": "公司年度总营收实现稳步增长 [1]。", "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}], "status": "succeeded"}, MagicMock(unattended=False), {})
        await asyncio.gather(*list(_TASKS))
        assert not judge_called

        # Check JSONL records
        records = [json.loads(line) for line in list(tmp_path.glob("*.jsonl"))[0].read_text().splitlines()]
        t1_rec = next(r for r in records if r["turn_id"] == "t1")
        t2_rec = next(r for r in records if r["turn_id"] == "t2")
        t3_rec = next(r for r in records if r["turn_id"] == "t3")
        t4_rec = next(r for r in records if r["turn_id"] == "t4")
        t5_rec = next(r for r in records if r["turn_id"] == "t5")

        assert t1_rec["counted"] is False  # All failed
        assert t2_rec["counted"] is True
        assert t3_rec["counted"] is False  # Duplicate answer_sha256
        assert t4_rec["counted"] is True
        assert t5_rec["outcome"] == "target_reached"

    asyncio.run(_run())


def test_model_error_outcomes_and_secret_omission(monkeypatch, tmp_path: Path):
    """Catalog not found, key missing, model mismatch write corresponding outcomes.

    Secrets (fake api_key, identity_credential) never appear in JSONL.
    """
    async def _run():
        secret_key = "sk-super-secret-key-12345"
        secret_cred = "owner-secret-credential-98765"

        monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
        monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: True)

        # 1. Model mismatch
        set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "other-model", "api_key": secret_key}))
        maybe_schedule({"turn_id": "t_mismatch", "answer": "甲公司第三季度营收实现稳步增长 [1]。", "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}], "status": "succeeded"}, MagicMock(unattended=False, identity_credential=secret_cred), {})
        await asyncio.gather(*list(_TASKS))

        # 2. Key missing
        set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": ""}))
        maybe_schedule({"turn_id": "t_nokey", "answer": "乙公司第四季度利润实现大幅提升 [1]。", "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}], "status": "succeeded"}, MagicMock(unattended=False, identity_credential=secret_cred), {})
        await asyncio.gather(*list(_TASKS))

        content = list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8")
        assert "model_changed" in content
        assert "model_unavailable" in content

        # Assert secrets never leak to disk
        assert secret_key not in content
        assert secret_cred not in content

    asyncio.run(_run())


def test_rate_limit_circuit_breaker(monkeypatch, tmp_path: Path):
    """429 rate limit trips circuit breaker: remaining sentences skipped_rate_limited, next turn writes circuit_open."""
    async def _run():
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
        monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: True)

        set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "fake"}))

        call_count = 0

        async def rate_limiting_judge(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return JudgeResult(status="provider_error", error_code="provider_rate_or_quota_error")
            return JudgeResult(status="ok")

        set_test_judge_fn(rate_limiting_judge)

        turn1 = {
            "turn_id": "t_rate1",
            "answer": "公司第一季度营收实现稳步增长 [1]。公司第二季度利润实现大幅提升 [1]。",
            "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}],
            "status": "succeeded",
        }
        maybe_schedule(turn1, MagicMock(unattended=False), {})
        await asyncio.gather(*list(_TASKS))

        # Next turn immediately after
        turn2 = {
            "turn_id": "t_rate2",
            "answer": "公司第三季度业务实现稳步推进 [1]。",
            "citations": [{"ordinal": 1, "quote": "revenue rose steadily", "source_type": "official_filing"}],
            "status": "succeeded",
        }
        maybe_schedule(turn2, MagicMock(unattended=False), {})
        await asyncio.gather(*list(_TASKS))

        records = [json.loads(line) for line in list(tmp_path.glob("*.jsonl"))[0].read_text().splitlines()]
        r1 = next(r for r in records if r["turn_id"] == "t_rate1")
        r2 = next(r for r in records if r["turn_id"] == "t_rate2")

        assert r1["sentences"][0]["status"] == "provider_error"
        assert r1["sentences"][1]["status"] == "skipped_rate_limited"
        assert r2["outcome"] == "circuit_open"

    asyncio.run(_run())


def test_private_turn_leaves_no_raw_text(monkeypatch, tmp_path: Path):
    """If no_judgeable is due to private sources, question, answer, and sources must not be written."""
    async def _run():
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path.resolve()))
        monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
        monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda cred: True)

        secret_answer = "私人持仓数据秘密答案，用户持股十万股 [1]。"
        secret_question = "我的私人持仓有多少？"

        turn = {
            "turn_id": "t_priv",
            "answer": secret_answer,
            "citations": [{"ordinal": 1, "quote": "100000", "source_type": "portfolio"}],
            "status": "succeeded",
        }
        maybe_schedule(turn, MagicMock(unattended=False), {"question": secret_question})
        await asyncio.gather(*list(_TASKS))

        content = list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8")
        assert "no_judgeable" in content
        assert secret_answer not in content
        assert secret_question not in content
        assert "100000" not in content

    asyncio.run(_run())
