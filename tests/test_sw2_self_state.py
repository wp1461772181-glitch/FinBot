"""SW2 S2 (R1, R7; spec-sw2 §3.1, K6–K11): the model and the previous answer's system source check, as a fact block.

Pins P-R1 (the five states reach the model as the spec's wording), B1 (one ledger line per shadow terminal, written after
the gate returns), B2 (reason codes), B3 (turns from before the audit key), B4 (tail only, bad lines unknown), B5 (at most five
sentences of sixty characters), K6 (paused read), K8 (owner refusal writes nothing), K9 (wording, once per turn), K10 (what the
ledger keeps; file modes). Off: no block, no audit key, no ledger line.
"""
import asyncio
import json
import os
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_workflow import claim_public_wire as wire
from app.agent_workflow import claim_shadow
from app.agent_workflow import direct
from app.agent_workflow.state import AgentRuntimeContext

OWNER = "owner-credential-for-sw2-tests"
TURN = "11111111-2222-4333-8444-555555555555"
K9_PENDING = '- 上一条回答的系统来源核对：还没有结果（核对在回答之后另行进行，距上一条完成约 {s} 秒）；目前没有显示任何标注。'


@pytest.fixture(autouse=True)
def _switches(monkeypatch, tmp_path):
    for name in ("FINBOT_SW2_SELF_STATE", "FINBOT_SW2_MEMORY_PRELOAD", "FINBOT_SW2_SELF_STATE_WORDING", "FINBOT_SW2_HISTORY_PAGES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path))
    claim_shadow.reset_state()
    yield
    claim_shadow.reset_state()


def _marks(*sentences):
    return [{"id": f"m{i}", "hover": {"answer_sentence": s, "evidence": {}}} for i, s in enumerate(sentences)]


def _state(**kwargs):
    base = dict(model_label="haiku-5.5（openrouter/anthropic/claude-haiku-5-5）", prior=None)
    base.update(kwargs)
    return base


def _context(*, bot_id=None, self_state=None):
    return SimpleNamespace(provider="openrouter", model="anthropic/claude-haiku-5-5", bot_id=bot_id, self_state=self_state)


# ---- B2: maybe_schedule returns the reason its synchronous filter gave -------------------------------------------------

def _result(**overrides):
    base = {"status": "succeeded", "answer": "数字 [1]。", "citations": [{"ordinal": 1}], "turn_id": TURN}
    base.update(overrides)
    return base


def test_maybe_schedule_names_each_synchronous_reason(monkeypatch):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    ctx = SimpleNamespace(provider="p", model="m", identity_credential=OWNER, unattended=False, bot_id=None)
    assert claim_shadow.maybe_schedule(_result(pending_request={"id": "x"}), ctx, {}) == "pending_request"
    assert claim_shadow.maybe_schedule(_result(status="failed"), ctx, {}) == "not_succeeded"
    assert claim_shadow.maybe_schedule(_result(citations=[]), ctx, {}) == "no_numbered_sources"
    assert claim_shadow.maybe_schedule(_result(answer="没有编号。"), ctx, {}) == "no_numbered_sources"
    unattended = SimpleNamespace(provider="p", model="m", identity_credential=OWNER, unattended=True, bot_id=None)
    assert claim_shadow.maybe_schedule(_result(), unattended, {}) == "unattended"
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "off")
    assert claim_shadow.maybe_schedule(_result(), ctx, {}) == "shadow_off"


def test_maybe_schedule_busy_and_scheduled(monkeypatch):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    ctx = SimpleNamespace(provider="p", model="m", identity_credential=OWNER, unattended=False, bot_id=None)
    ran = []

    async def fake_run(snapshot):
        ran.append(snapshot.turn_id)

    monkeypatch.setattr(claim_shadow, "_run", fake_run)

    async def go():
        codes = [claim_shadow.maybe_schedule(_result(turn_id=f"{i:08d}-0000-4000-8000-000000000000"), ctx, {})
                 for i in range(claim_shadow.MAX_PENDING_TURNS + 1)]
        await asyncio.sleep(0)
        return codes
    codes = asyncio.run(go())
    assert codes[:claim_shadow.MAX_PENDING_TURNS] == ["scheduled"] * claim_shadow.MAX_PENDING_TURNS
    assert codes[-1] == "busy" and len(ran) == claim_shadow.MAX_PENDING_TURNS


# ---- K9 / B5 / P-R6 SELF_MODEL & SELF_NO_BOT: the fact block itself ----------------------------------------------------

def test_fact_block_has_model_no_bot_and_the_shown_list_capped_at_five(monkeypatch):
    sentences = [f"句子{i}" + "甲" * 80 for i in range(7)]
    text, audit = direct.self_state_block(_context(self_state=_state(prior={"state": "shown", "sentences": sentences}, )))
    lines = text.split("\n")
    assert lines[0] == direct.SELF_STATE_HEAD
    assert lines[1] == "- 当前回答模型：haiku-5.5（openrouter/anthropic/claude-haiku-5-5）"
    assert direct.SELF_NO_BOT in lines
    shown = [l for l in lines if "公开显示了" in l][0]
    assert shown.endswith("；等 7 处。")
    assert shown.count("；") == 5                                # five listed, then the count
    assert shown.count("甲") <= 5 * 60
    assert audit["prior_state"] == "shown" and audit["prior_shown"] == 7
    assert direct.SELF_PRIOR_NOTE in lines


def test_bot_turn_has_no_no_bot_line():
    text, _ = direct.self_state_block(_context(bot_id="b1", self_state=_state()))
    assert direct.SELF_NO_BOT not in text and "- 当前回答模型：" in text


def test_pending_wording_is_the_accepted_text_and_rounds_up_to_one_second():
    text, audit = direct.self_state_block(_context(self_state=_state(prior={"state": "pending", "elapsed_s": 0.2})))
    assert K9_PENDING.format(s=1) in text.split("\n")
    assert audit["prior_state"] == "pending"


def test_fact_block_never_carries_a_judge_field():
    sentences = ["Northwind 第三季度营收下降 8%"]
    text, _ = direct.self_state_block(_context(self_state=_state(prior={"state": "shown", "sentences": sentences})))
    for word in ("verdict", "not_in_source", "reason", "contradiction", "judge"):
        assert word not in text


# ---- P-R1 at the level of the states: prior_answer_state decides, the block says ----------------------------------------

@pytest.mark.parametrize("name,audit,marks,settled,paused,elapsed,expected", [
    ("judged-no-marks", {"judge_schedule": "scheduled"}, [], {"outcome": "judged"}, False, 5.0, {"state": "none"}),
    ("judged-two-marks", {"judge_schedule": "scheduled"}, ["甲", "乙"], {"outcome": "judged"}, False, 5.0, "shown"),
    ("pending", {"judge_schedule": "scheduled"}, [], None, False, 12.0, {"state": "pending", "elapsed_s": 12.0}),
    ("stale-unknown", {"judge_schedule": "scheduled"}, [], None, False, 400.0, {"state": "unknown"}),
    ("paused", {"judge_schedule": "scheduled"}, [], None, True, 5.0, {"state": "paused"}),
    ("no-numbered", {"judge_schedule": "no_numbered_sources"}, [], None, False, 5.0, {"state": "not_checked", "reason": "no_numbered_sources"}),
    ("stopped", {"judge_schedule": "scheduled"}, [], {"outcome": "stopped"}, False, 5.0, {"state": "not_checked", "reason": "shadow_off"}),
    ("error", {"judge_schedule": "scheduled"}, [], {"outcome": "error"}, False, 5.0, {"state": "not_checked", "reason": "unavailable"}),
])
def test_prior_answer_state_table(monkeypatch, name, audit, marks, settled, paused, elapsed, expected):
    monkeypatch.setattr(wire, "prior_turn_marks", lambda turn_id: (paused, _marks(*marks)))
    monkeypatch.setattr(wire, "read_settled", lambda turn_id: settled)
    state = wire.prior_answer_state(TURN, owner=True, audit=audit, elapsed_s=elapsed)
    if expected == "shown":
        assert state["state"] == "shown" and len(state["sentences"]) == len(marks)
    else:
        assert {k: v for k, v in state.items() if k != "sentences"} == expected


def test_not_owner_is_not_checked_without_reading_anything(monkeypatch):
    monkeypatch.setattr(wire, "read_settled", lambda *_: pytest.fail("the ledger must not be read for a guest"))
    assert wire.prior_answer_state(TURN, owner=False, audit={"judge_schedule": "scheduled"}, elapsed_s=1) == {
        "state": "not_checked", "reason": "not_owner"}


def test_turn_from_before_the_audit_key_shows_marks_or_unknown(monkeypatch):
    monkeypatch.setattr(wire, "prior_turn_marks", lambda turn_id: (False, _marks("甲")))
    assert wire.prior_answer_state(TURN, owner=True, audit={}, elapsed_s=1)["state"] == "shown"
    monkeypatch.setattr(wire, "prior_turn_marks", lambda turn_id: (False, []))
    assert wire.prior_answer_state(TURN, owner=True, audit=None, elapsed_s=1) == {"state": "unknown"}


# ---- K6: prior_turn_marks reads the pause and missing state as the public read does -------------------------------------

def test_prior_turn_marks_pause_and_missing_state_are_different(tmp_path, monkeypatch):
    assert wire.prior_turn_marks(TURN) == (False, [])          # no state file: not paused
    (tmp_path / wire.STATE_NAME).write_text(json.dumps({"paused": True, "displayed": []}), encoding="utf-8")
    assert wire.prior_turn_marks(TURN) == (True, [])           # paused
    (tmp_path / wire.STATE_NAME).write_text(json.dumps({"paused": False, "displayed": []}), encoding="utf-8")
    assert wire.prior_turn_marks(TURN) == (False, [])          # not paused, nothing displayed


# ---- B4 / K10: the ledger is tail-read, tolerant, and keeps only turn_id, outcome, at -----------------------------------

def test_ledger_keeps_three_keys_and_private_modes(tmp_path):
    shadow = tmp_path / "shadow"                                  # created by the ledger write: 0700
    wire.append_settled(shadow, TURN, "judged")
    row = json.loads((shadow / wire.SETTLED_NAME).read_text(encoding="utf-8").strip())
    assert set(row) == {"turn_id", "outcome", "at"} and row["turn_id"] == TURN and row["outcome"] == "judged"
    assert stat.S_IMODE(os.stat(shadow / wire.SETTLED_NAME).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(shadow).st_mode) == 0o700


def test_tail_only_and_bad_lines_are_unknown_not_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(wire, "SETTLED_TAIL_LINES", 5)
    old = "99999999-0000-4000-8000-000000000000"
    path = tmp_path / wire.SETTLED_NAME
    rows = [json.dumps({"turn_id": old, "outcome": "judged", "at": "x"})]
    rows += ["not json at all"]
    rows += [json.dumps({"turn_id": f"{i:08d}-0000-4000-8000-000000000000", "outcome": "judged", "at": "x"}) for i in range(10)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path))
    assert wire.read_settled(old) is None                      # older than the tail: never read
    assert wire.read_settled(f"{9:08d}-0000-4000-8000-000000000000")["outcome"] == "judged"
    (tmp_path / wire.SETTLED_NAME).unlink()
    assert wire.read_settled(TURN) is None                     # missing file: unknown, no exception


# ---- The turn: the fact block reaches the model, once per turn, and the audit records what it said --------------------

def _run_turn(monkeypatch, *, self_state, bot_id=None):
    from app.agent_workflow.direct import run_direct_turn
    from test_sw1b_closing_complete import text
    seen = []
    monkeypatch.setattr(direct, "owner_credential_matches", lambda c: c == OWNER)

    def decide(messages, offered):
        seen.append(messages)
        return text("这是一个没有编号的回答。")

    async def emit(_event):
        pass
    ctx = AgentRuntimeContext("custom", "test", "dummy", identity_credential=OWNER, classifier=lambda _: {
        "category": "A", "mode": "rag", "symbol": None, "symbols": [], "days_back": None}, decider=decide,
        self_state=self_state, bot_id=bot_id)
    result = asyncio.run(run_direct_turn("你用的哪个模型？", ctx, emit=emit))
    return result, seen[0]


def _block_lines(messages):
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system" and str(m.get("content") or "").startswith(direct.SELF_STATE_HEAD):
            return str(m["content"]).split("\n")
    return None


@pytest.mark.parametrize("prior,line", [
    ({"state": "none"}, "- 上一条回答的系统来源核对：已完成，没有显示任何标注。"),
    ({"state": "shown", "sentences": ["甲"]}, "- 上一条回答的系统来源核对：已完成，公开显示了 1 处标注，分别在：甲。"),
    ({"state": "pending", "elapsed_s": 12.4}, K9_PENDING.format(s=12)),
    ({"state": "paused"}, "- 上一条回答的系统来源核对：标注展示目前暂停，看不到结果。"),
    ({"state": "not_checked", "reason": "no_numbered_sources"}, "- 上一条回答的系统来源核对：这条没有做（上一条没有带编号的来源）。"),
    ({"state": "unknown"}, "- 上一条回答的系统来源核对：查不到这条的结果。"),
])
def test_each_state_line_reaches_the_model_verbatim(monkeypatch, disposable_database, prior, line):
    state = _state(prior={**prior, "turn_id": TURN}, prior_elapsed_s=prior.get("elapsed_s", 0.0))
    result, messages = _run_turn(monkeypatch, self_state=state)
    lines = _block_lines(messages)
    assert lines is not None and line in lines
    assert lines[1] == "- 当前回答模型：haiku-5.5（openrouter/anthropic/claude-haiku-5-5）"
    assert result["audit"]["self_state"]["prior_state"] == prior["state"]


def test_switch_off_sends_no_block_and_writes_no_audit(monkeypatch, disposable_database):
    monkeypatch.setenv("FINBOT_SW2_SELF_STATE", "off")
    result, messages = _run_turn(monkeypatch, self_state=_state(prior={"state": "none", "turn_id": TURN}))
    assert _block_lines(messages) is None
    assert "self_state" not in result["audit"]


def test_model_line_is_the_only_line_when_there_is_no_previous_answer(monkeypatch, disposable_database):
    result, messages = _run_turn(monkeypatch, self_state=_state(prior=None))
    lines = _block_lines(messages)
    assert lines == [direct.SELF_STATE_HEAD, "- 当前回答模型：haiku-5.5（openrouter/anthropic/claude-haiku-5-5）", direct.SELF_NO_BOT]
    assert result["audit"]["self_state"] == {"model_label": "haiku-5.5（openrouter/anthropic/claude-haiku-5-5）"}


# ---- B1: the shadow task's terminal writes: one line each, judged after the gate returns, owner refusal writes none --

def _snapshot(identity=OWNER, citations=True):
    return claim_shadow.ShadowTurn(
        turn_id=TURN, conversation_id="c1", bot_id=None, question="Northwind 营收？",
        answer="Northwind 第三季度营收下降 8% [1]。", status="succeeded", reason="normal", route="A",
        citations=({"ordinal": 1, "quote": "revenue rose 8%", "source_type": "official_filing",
                    "saved_text": "full_document", "check_text": "revenue rose 8% in Q3"},) if citations else (),
        code_flags={}, answer_model="openrouter/deepseek/deepseek-v4-flash", identity_credential=identity)


def _ledger(tmp_path):
    path = tmp_path / wire.SETTLED_NAME
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.fixture
def shadow_owner(monkeypatch):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda c: c == OWNER)
    claim_shadow.set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "k"}))
    yield
    claim_shadow.set_test_resolve_fn(None)


def test_judged_turn_writes_one_line_after_the_gate_returns(monkeypatch, tmp_path, shadow_owner):
    from app.agent_workflow.claim_judge import JudgeResult
    monkeypatch.setattr("app.agent_workflow.claim_judge.judge_claims", AsyncMock(return_value=JudgeResult(
        status="ok", verdict="ok", reason="", quote="revenue rose 8%", quote_verified=True, quote_ordinal=1, subtype="number")))
    monkeypatch.setattr("app.agent_workflow.claim_short_review.review_candidate", AsyncMock(return_value={"status": "ok", "passed": True}))
    seen_at_gate = []
    original = wire.process_record

    def spy(dir_path, record):
        seen_at_gate.append(len(_ledger(tmp_path)))       # the ledger must not have the line yet
        return original(dir_path, record)
    monkeypatch.setattr(wire, "process_record", spy)
    asyncio.run(claim_shadow._run(_snapshot()))
    assert seen_at_gate == [0]
    assert [r["outcome"] for r in _ledger(tmp_path)] == ["judged"]


def test_stopped_turn_writes_stopped_once(monkeypatch, tmp_path, shadow_owner):
    (tmp_path / "STOP").write_text("STOP", encoding="utf-8")
    asyncio.run(claim_shadow._run(_snapshot()))
    assert [r["outcome"] for r in _ledger(tmp_path)] == ["stopped"]


def test_owner_refusal_writes_no_line(monkeypatch, tmp_path, shadow_owner):
    asyncio.run(claim_shadow._run(_snapshot(identity="guest-credential")))
    assert _ledger(tmp_path) == []


def test_settle_failure_is_logged_and_the_turn_still_judges(monkeypatch, tmp_path, shadow_owner):
    from app.agent_workflow.claim_judge import JudgeResult
    monkeypatch.setattr("app.agent_workflow.claim_judge.judge_claims", AsyncMock(return_value=JudgeResult(
        status="ok", verdict="ok", reason="", quote="revenue rose 8%", quote_verified=True, quote_ordinal=1, subtype="number")))
    monkeypatch.setattr("app.agent_workflow.claim_short_review.review_candidate", AsyncMock(return_value={"status": "ok", "passed": True}))

    def broken(*_args, **_kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(wire, "append_settled", broken)
    asyncio.run(claim_shadow._run(_snapshot()))
    assert len(list(tmp_path.glob("[0-9]*.jsonl"))) == 1         # the shadow record is still written
    assert _ledger(tmp_path) == []                               # and the failed ledger line is not
